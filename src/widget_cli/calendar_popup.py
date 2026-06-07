"""On-demand calendar popup — GTK4 dialog.

Shows a month grid with busy days marked, click a day to see/add that
day's tasks. Inline add: title field + project picker + Add button
inside the popup itself so the flow stays in one window.
"""

from __future__ import annotations

import argparse
import calendar as calendar_mod
import threading
from datetime import date
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .shared.format import fetch_project_map, parse_validation_error  # noqa: E402
from .shared.fetcher_signal import wake_fetcher  # noqa: E402
from .shared.http import client  # noqa: E402
from .shared.notify import toast  # noqa: E402


def _fetch_open_tasks() -> list[dict[str, Any]]:
    """Pull every open task — the popup only ever filters client-side."""
    out: list[dict[str, Any]] = []
    with client() as c:
        for status in ("not_yet", "doing"):
            r = c.get("/api/v1/tasks", params={"status": status, "limit": 500})
            if r.status_code != 200:
                continue
            body = r.json()
            items = body.get("data") if isinstance(body, dict) else body
            out.extend(items or [])
    return out


def _fetch_projects() -> dict[str, str]:
    with client() as c:
        return fetch_project_map(c)


def _filter_tasks_for_day(tasks: list[dict[str, Any]], d: date) -> list[dict[str, Any]]:
    """Match either scheduled_date == d or deadline's date-part == d."""
    iso = d.isoformat()
    out: list[dict[str, Any]] = []
    for t in tasks:
        if t.get("scheduled_date") == iso:
            out.append(t)
            continue
        raw_dl = t.get("deadline")
        if raw_dl and raw_dl[:10] == iso:
            out.append(t)
    out.sort(key=lambda x: x.get("fixed_start_time") or "ZZ")
    return out


def _post_task(payload: dict[str, Any]) -> tuple[bool, str]:
    with client() as c:
        r = c.post("/api/v1/tasks", json=payload)
        if r.status_code in (200, 201):
            return True, ""
        return False, parse_validation_error(r.status_code, r.text)


# ── Badge rendering for day-detail rows ──────────────────────────────────────


_PRI_BADGE = {1: "L", 2: "M", 3: "H"}


def _task_row_text(t: dict[str, Any], project_name: str | None) -> str:
    parts: list[str] = []
    time_part = (t.get("fixed_start_time") or "")[:5]
    if time_part:
        parts.append(time_part)
    parts.append(t.get("title") or "(no title)")
    if project_name:
        parts.append(f"#{project_name}")
    pri = int(t.get("priority") or 0)
    if pri in _PRI_BADGE:
        parts.append(f"[{_PRI_BADGE[pri]}]")
    if t.get("is_important"):
        parts.append("★")
    if t.get("is_urgent"):
        parts.append("!")
    return "  ".join(parts)


# ── GTK window ───────────────────────────────────────────────────────────────


class CalendarWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application) -> None:
        super().__init__(application=app, title="Calendar")
        self.set_default_size(380, 600)
        self.set_resizable(False)

        today = date.today()
        self._selected: date = today
        self._tasks: list[dict[str, Any]] = []
        self._projects: dict[str, str] = {}
        self._current_year = today.year
        self._current_month = today.month

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        self.set_child(box)

        # ── Month grid ────────────────────────────────────────────────
        self._calendar = Gtk.Calendar()
        self._calendar.connect("day-selected", self._on_day_selected)
        self._calendar.connect("next-month", self._on_month_changed)
        self._calendar.connect("prev-month", self._on_month_changed)
        self._calendar.connect("next-year", self._on_month_changed)
        self._calendar.connect("prev-year", self._on_month_changed)
        box.append(self._calendar)

        # ── Day detail header ─────────────────────────────────────────
        self._detail_header = Gtk.Label(xalign=0.0)
        self._detail_header.add_css_class("title-3")
        box.append(self._detail_header)

        # ── Scrollable task list ──────────────────────────────────────
        scroller = Gtk.ScrolledWindow(vexpand=True)
        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller.set_child(self._list_box)
        box.append(scroller)

        # ── Inline add row: title entry + project dropdown + button ──
        add_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._title_entry = Gtk.Entry()
        self._title_entry.set_placeholder_text("New task title…")
        self._title_entry.set_hexpand(True)
        # Pressing Enter inside the entry triggers the add too.
        self._title_entry.connect("activate", self._on_add_clicked)
        add_box.append(self._title_entry)

        self._project_combo = Gtk.ComboBoxText()
        self._project_combo.append(id="", text="📥 Inbox")
        add_box.append(self._project_combo)

        self._add_btn = Gtk.Button(label="Add")
        self._add_btn.connect("clicked", self._on_add_clicked)
        add_box.append(self._add_btn)
        box.append(add_box)

        # Escape closes — behave like a transient menu.
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key)

        self._kick_off_load()

    # ── data loading ───────────────────────────────────────────────────

    def _kick_off_load(self) -> None:
        def worker() -> None:
            try:
                tasks = _fetch_open_tasks()
                projects = _fetch_projects()
            except Exception as e:  # noqa: BLE001
                GLib.idle_add(self._on_load_failed, str(e))
                return
            GLib.idle_add(self._on_load_done, tasks, projects)

        threading.Thread(target=worker, daemon=True).start()

    def _on_load_done(self, tasks: list[dict[str, Any]], projects: dict[str, str]) -> bool:
        self._tasks = tasks
        self._projects = projects
        # Re-populate the project dropdown only the first time around so
        # navigating months doesn't reset the user's chosen project.
        if self._project_combo.get_active() < 0:
            self._project_combo.set_active(0)
            for pid, pname in sorted(projects.items(), key=lambda kv: kv[1].lower()):
                self._project_combo.append(id=pid, text=f"#{pname}")
        self._refresh_marks()
        self._refresh_detail()
        return False

    def _on_load_failed(self, msg: str) -> bool:
        toast("Calendar load failed", msg, urgent=True)
        return False

    # ── marks ──────────────────────────────────────────────────────────

    def _refresh_marks(self) -> None:
        self._calendar.clear_marks()
        target_y = self._current_year
        target_m = self._current_month
        for t in self._tasks:
            for key in ("scheduled_date", "deadline"):
                v = t.get(key)
                if not v:
                    continue
                try:
                    d = date.fromisoformat(v[:10])
                except ValueError:
                    continue
                if d.year == target_y and d.month == target_m:
                    self._calendar.mark_day(d.day)

    # ── detail pane ────────────────────────────────────────────────────

    def _refresh_detail(self) -> None:
        self._detail_header.set_text(self._selected.isoformat())
        while (row := self._list_box.get_first_child()) is not None:
            self._list_box.remove(row)
        items = _filter_tasks_for_day(self._tasks, self._selected)
        if not items:
            label = Gtk.Label(label="(nothing scheduled)", xalign=0.0)
            label.add_css_class("dim-label")
            label.set_margin_top(6)
            label.set_margin_bottom(6)
            label.set_margin_start(6)
            row = Gtk.ListBoxRow()
            row.set_child(label)
            self._list_box.append(row)
            return
        for t in items:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(xalign=0.0, wrap=True)
            label.set_text(
                _task_row_text(t, project_name=self._projects.get(t.get("project_id")))
            )
            label.set_margin_top(4)
            label.set_margin_bottom(4)
            label.set_margin_start(6)
            label.set_margin_end(6)
            row.set_child(label)
            self._list_box.append(row)

    # ── inline add ─────────────────────────────────────────────────────

    def _on_add_clicked(self, _w) -> None:
        title = self._title_entry.get_text().strip()
        if not title:
            return
        project_id = self._project_combo.get_active_id() or None
        payload: dict[str, Any] = {
            "title": title,
            "scheduled_date": self._selected.isoformat(),
        }
        if project_id:
            payload["project_id"] = project_id

        def worker() -> None:
            ok, err = _post_task(payload)
            if not ok:
                GLib.idle_add(self._on_add_failed, err)
                return
            GLib.idle_add(self._on_add_done, title)

        # Lock the button so double-click doesn't double-submit.
        self._add_btn.set_sensitive(False)
        threading.Thread(target=worker, daemon=True).start()

    def _on_add_done(self, title: str) -> bool:
        self._title_entry.set_text("")
        self._add_btn.set_sensitive(True)
        toast("Task added", f"{title}  ·  {self._selected.isoformat()}")
        wake_fetcher()
        # Re-pull so the just-added task appears in the day list.
        self._kick_off_load()
        return False

    def _on_add_failed(self, err: str) -> bool:
        self._add_btn.set_sensitive(True)
        toast("Add failed", err, urgent=True)
        return False

    # ── signal handlers ────────────────────────────────────────────────

    def _selected_from_calendar(self) -> date:
        dt = self._calendar.get_date()
        return date(dt.get_year(), dt.get_month(), dt.get_day_of_month())

    def _on_day_selected(self, _cal: Gtk.Calendar) -> None:
        self._selected = self._selected_from_calendar()
        self._refresh_detail()

    def _on_month_changed(self, _cal: Gtk.Calendar) -> None:
        sel = self._selected_from_calendar()
        self._current_year = sel.year
        self._current_month = sel.month
        self._kick_off_load()

    def _on_key_pressed(self, _ctrl, keyval, _keycode, _mods) -> bool:
        from gi.repository import Gdk

        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False


class CalendarApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="org.wayland-conky.Calendar")

    def do_activate(self) -> None:
        win = CalendarWindow(self)
        win.present()
        _ = calendar_mod  # silence unused-import linter


def main(_args: argparse.Namespace) -> int:
    app = CalendarApp()
    return app.run(None) or 0


def add_args(_p: argparse.ArgumentParser) -> None:
    pass
