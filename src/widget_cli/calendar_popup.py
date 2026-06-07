"""GTK4 + libadwaita calendar popup.

Shows a month grid with busy days marked, click a day to see the
tasks scheduled / deadlined that day. "Add task for this day" opens
the unified TaskForm prefilled with the selected date, so users see
the same surface no matter which entry point they choose.
"""

from __future__ import annotations

import argparse
import threading
from datetime import date
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from . import task_form  # noqa: E402
from .shared.fetcher_signal import wake_fetcher  # noqa: E402
from .shared.format import fetch_project_map  # noqa: E402
from .shared.http import client  # noqa: E402
from .shared.notify import toast  # noqa: E402
from .shared.theme import apply_theme  # noqa: E402


def _fetch_open_tasks() -> list[dict[str, Any]]:
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


_PRI_BADGE = {1: "L", 2: "M", 3: "H"}


# ── Window ────────────────────────────────────────────────────────────────


class CalendarWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="Calendar")
        self.set_default_size(420, 640)

        today = date.today()
        self._selected: date = today
        self._tasks: list[dict[str, Any]] = []
        self._projects: dict[str, str] = {}
        self._current_year = today.year
        self._current_month = today.month

        overlay = Adw.ToastOverlay()
        self._overlay = overlay
        self.set_content(overlay)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        overlay.set_child(root)

        header = Adw.HeaderBar()
        root.append(header)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        clamp = Adw.Clamp(maximum_size=460, tightening_threshold=420)
        page = Adw.PreferencesPage()
        clamp.set_child(page)
        scroll.set_child(clamp)
        root.append(scroll)

        # ── Group: Month grid ────────────────────────────────────────
        grid_group = Adw.PreferencesGroup()
        page.add(grid_group)
        cal_row = Adw.PreferencesRow()
        cal_row.set_activatable(False)
        cal_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        cal_box.set_margin_top(8)
        cal_box.set_margin_bottom(8)
        cal_box.set_margin_start(8)
        cal_box.set_margin_end(8)
        self._calendar = Gtk.Calendar()
        self._calendar.connect("day-selected", self._on_day_selected)
        self._calendar.connect("next-month", self._on_month_changed)
        self._calendar.connect("prev-month", self._on_month_changed)
        self._calendar.connect("next-year", self._on_month_changed)
        self._calendar.connect("prev-year", self._on_month_changed)
        cal_box.append(self._calendar)
        cal_row.set_child(cal_box)
        grid_group.add(cal_row)

        # ── Group: Day detail ────────────────────────────────────────
        self._detail_group = Adw.PreferencesGroup()
        page.add(self._detail_group)
        self._refresh_detail_group_header()

        # ── Add button ───────────────────────────────────────────────
        add_group = Adw.PreferencesGroup()
        page.add(add_group)
        add_row = Adw.ActionRow(title="+ Add task for this day")
        add_row.set_activatable(True)
        add_row.connect("activated", lambda _r: self._on_add_clicked())
        # Make the row look like a primary action.
        add_row.add_css_class("accent")
        add_group.add(add_row)
        self._add_row = add_row

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)

        self._kick_off_load()

    # ── data ───────────────────────────────────────────────────────────

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

    def _on_load_done(
        self, tasks: list[dict[str, Any]], projects: dict[str, str]
    ) -> bool:
        self._tasks = tasks
        self._projects = projects
        self._refresh_marks()
        self._refresh_detail()
        return False

    def _on_load_failed(self, msg: str) -> bool:
        toast("Calendar load failed", msg, urgent=True)
        return False

    # ── marks ──────────────────────────────────────────────────────────

    def _refresh_marks(self) -> None:
        self._calendar.clear_marks()
        for t in self._tasks:
            for key in ("scheduled_date", "deadline"):
                v = t.get(key)
                if not v:
                    continue
                try:
                    d = date.fromisoformat(v[:10])
                except ValueError:
                    continue
                if (
                    d.year == self._current_year
                    and d.month == self._current_month
                ):
                    self._calendar.mark_day(d.day)

    # ── detail ─────────────────────────────────────────────────────────

    def _refresh_detail_group_header(self) -> None:
        self._detail_group.set_title(self._selected.isoformat())

    def _refresh_detail(self) -> None:
        self._refresh_detail_group_header()
        # Adw.PreferencesGroup doesn't expose row removal; we wipe via
        # its internal Gtk.ListBox if accessible. Simplest path: track
        # rows we added and remove them by reference.
        for row in getattr(self, "_detail_rows", []):
            self._detail_group.remove(row)
        self._detail_rows: list[Gtk.Widget] = []

        items = _filter_tasks_for_day(self._tasks, self._selected)
        if not items:
            row = Adw.ActionRow(
                title="(nothing scheduled)",
                css_classes=["dim-label"],
            )
            self._detail_group.add(row)
            self._detail_rows.append(row)
            return
        for t in items:
            title = t.get("title") or "(no title)"
            subtitle_parts: list[str] = []
            time_part = (t.get("fixed_start_time") or "")[:5]
            if time_part:
                subtitle_parts.append(time_part)
            pname = self._projects.get(t.get("project_id"))
            if pname:
                subtitle_parts.append(f"#{pname}")
            pri = int(t.get("priority") or 0)
            if pri in _PRI_BADGE:
                subtitle_parts.append(f"[{_PRI_BADGE[pri]}]")
            if t.get("is_important"):
                subtitle_parts.append("★")
            if t.get("is_urgent"):
                subtitle_parts.append("!")
            row = Adw.ActionRow(
                title=title,
                subtitle="  ·  ".join(subtitle_parts) if subtitle_parts else None,
            )
            self._detail_group.add(row)
            self._detail_rows.append(row)

    # ── handlers ───────────────────────────────────────────────────────

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

    def _on_add_clicked(self) -> None:
        def on_created(_created: dict) -> None:
            wake_fetcher()
            GLib.idle_add(self._kick_off_load)

        task_form.show(initial_date=self._selected, on_created=on_created)

    def _on_key(self, _ctrl, keyval, _kc, _mods) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False


# ── App entry ──────────────────────────────────────────────────────────────


class CalendarApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id="org.wayland-conky.Calendar")

    def do_activate(self) -> None:
        apply_theme()
        win = CalendarWindow(self)
        win.present()


def main(_args: argparse.Namespace) -> int:
    app = CalendarApp()
    return app.run(None) or 0


def add_args(_p: argparse.ArgumentParser) -> None:
    pass
