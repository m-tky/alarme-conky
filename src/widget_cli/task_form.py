"""GTK4 + libadwaita task creation form.

Libadwaita gives us first-class form rows (EntryRow, ComboRow,
SpinRow, SwitchRow, ExpanderRow) and a header bar that follows the
system Light/Dark theme without any CSS work — the surface looks at
home next to GNOME's own dialogs.

Keyboard flow contract:
- Title is focused on open. Hitting Enter from Title submits with
  every other field at defaults — that's the "quick capture" speed.
- Tab cycles through the rows in declaration order, Shift+Tab goes
  back, Esc cancels.
- Date / time entries accept both popover picker clicks and direct
  typing (YYYY-MM-DD / HH:MM).

The form is also the calendar-popup add path: ``show(initial_date=…)``
prefills the scheduled date so clicking a day in the calendar opens
the form already pointed at that day.
"""

from __future__ import annotations

import re
import threading
from datetime import UTC, date, datetime
from typing import Any, Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from .shared.fetcher_signal import wake_fetcher  # noqa: E402
from .shared.format import fetch_project_map, parse_validation_error  # noqa: E402
from .shared.http import client  # noqa: E402
from .shared.notify import toast  # noqa: E402
from .shared.theme import apply_theme  # noqa: E402


_HHMM = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")
_YMD = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*$")


# ── Data fetching ────────────────────────────────────────────────────────────


def _fetch_projects_and_tags() -> tuple[dict[str, str], list[dict[str, Any]]]:
    projects: dict[str, str] = {}
    tags: list[dict[str, Any]] = []
    with client() as c:
        projects = fetch_project_map(c)
        r = c.get("/api/v1/tags")
        if r.status_code == 200:
            body = r.json()
            items = body if isinstance(body, list) else (body.get("data") or [])
            tags = [t for t in items if isinstance(t, dict)]
    return projects, tags


def _create_tag(name: str) -> str | None:
    with client() as c:
        r = c.post("/api/v1/tags", json={"name": name})
        if r.status_code in (200, 201):
            return r.json().get("id")
    return None


def _post_task(payload: dict[str, Any]) -> tuple[dict | None, str]:
    with client() as c:
        r = c.post("/api/v1/tasks", json=payload)
        if r.status_code in (200, 201):
            return r.json(), ""
        return None, parse_validation_error(r.status_code, r.text)


# ── Parsing helpers ─────────────────────────────────────────────────────────


def _parse_date(text: str) -> date | None:
    m = _YMD.match(text or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _parse_hhmm(text: str) -> tuple[int, int] | None:
    m = _HHMM.match(text or "")
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if 0 <= h < 24 and 0 <= mi < 60:
        return h, mi
    return None


# ── Date + time expander row ────────────────────────────────────────────────


class _DateTimeRow(Adw.ExpanderRow):
    """ExpanderRow whose subtitle shows the current selection and whose
    expanded body is a GtkCalendar + HH:MM entry. Editing either side
    updates the subtitle so the user can see the state without
    re-expanding."""

    def __init__(self, title: str, initial_date: date | None = None) -> None:
        super().__init__(title=title)
        self.set_show_enable_switch(True)
        self.set_enable_expansion(initial_date is not None)
        self._calendar = Gtk.Calendar()
        if initial_date is not None:
            self._calendar.select_day(
                GLib.DateTime.new_local(
                    initial_date.year, initial_date.month, initial_date.day, 0, 0, 0
                )
            )
        self._calendar.set_margin_top(8)
        self._calendar.set_margin_bottom(8)
        self._calendar.set_margin_start(12)
        self._calendar.set_margin_end(12)
        self._calendar.connect("day-selected", self._on_changed)
        self.add_row(_wrap_widget(self._calendar))

        self._time_row = Adw.EntryRow(title="Time (HH:MM)")
        self._time_row.connect("changed", self._on_changed)
        self.add_row(self._time_row)

        self.connect("notify::enable-expansion", self._on_changed)
        self._update_subtitle()

    def _on_changed(self, *_args) -> None:
        self._update_subtitle()

    def _update_subtitle(self) -> None:
        if not self.get_enable_expansion():
            self.set_subtitle("Off")
            return
        d = self.date_value()
        t = self.time_value()
        parts: list[str] = []
        if d is not None:
            parts.append(d.isoformat())
        if t is not None:
            parts.append(f"{t[0]:02d}:{t[1]:02d}")
        self.set_subtitle("  ·  ".join(parts) if parts else "Off")

    def date_value(self) -> date | None:
        if not self.get_enable_expansion():
            return None
        dt = self._calendar.get_date()
        return date(dt.get_year(), dt.get_month(), dt.get_day_of_month())

    def time_value(self) -> tuple[int, int] | None:
        if not self.get_enable_expansion():
            return None
        return _parse_hhmm(self._time_row.get_text())


def _wrap_widget(child: Gtk.Widget) -> Gtk.ListBoxRow:
    row = Gtk.ListBoxRow(activatable=False, selectable=False)
    row.set_child(child)
    return row


# ── Priority — linked segmented buttons in an ActionRow ──────────────────────


class _PriorityRow(Adw.ActionRow):
    LABELS = ["None", "Low", "Med", "High"]
    VALUES = [0, 1, 2, 3]

    def __init__(self) -> None:
        super().__init__(title="Priority")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        box.add_css_class("linked")
        box.set_valign(Gtk.Align.CENTER)
        self._buttons: list[Gtk.ToggleButton] = []
        group: Gtk.ToggleButton | None = None
        for label, val in zip(self.LABELS, self.VALUES):
            btn = Gtk.ToggleButton(label=label)
            if group is None:
                group = btn
            else:
                btn.set_group(group)
            if val == 0:
                btn.set_active(True)
            box.append(btn)
            self._buttons.append(btn)
        self.add_suffix(box)

    def value(self) -> int:
        for btn, val in zip(self._buttons, self.VALUES):
            if btn.get_active():
                return val
        return 0


# ── Tags row — chip flow + entry, gathered into an ActionRow body ────────────


class _TagsRow(Adw.PreferencesRow):
    def __init__(self, tags: list[dict[str, Any]]) -> None:
        super().__init__()
        self.set_activatable(False)
        self._known = {t["name"].lower(): t for t in tags if "name" in t}
        self._selected: list[tuple[str | None, str]] = []

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.set_margin_top(10)
        outer.set_margin_bottom(10)
        outer.set_margin_start(12)
        outer.set_margin_end(12)
        title = Gtk.Label(label="Tags", xalign=0.0)
        title.add_css_class("dim-label")
        outer.append(title)

        self._entry = Gtk.Entry(placeholder_text="Tag name + Enter")
        self._entry.connect("activate", self._on_activate)
        outer.append(self._entry)

        self._chips_box = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            max_children_per_line=8,
            homogeneous=False,
            column_spacing=4,
            row_spacing=4,
        )
        outer.append(self._chips_box)
        self.set_child(outer)

    def _on_activate(self, _entry: Gtk.Entry) -> None:
        name = self._entry.get_text().strip()
        if not name:
            return
        if any(n.lower() == name.lower() for _, n in self._selected):
            self._entry.set_text("")
            return
        match = self._known.get(name.lower())
        self._selected.append((match["id"] if match else None, name))
        self._render_chip(name)
        self._entry.set_text("")

    def _render_chip(self, name: str) -> None:
        chip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        chip.add_css_class("pill")
        chip.add_css_class("card")
        lbl = Gtk.Label(label=f"#{name}")
        lbl.set_margin_start(8)
        chip.append(lbl)
        close = Gtk.Button(icon_name="window-close-symbolic")
        close.add_css_class("flat")
        close.connect("clicked", lambda _b: self._remove(name, chip))
        chip.append(close)
        self._chips_box.append(chip)

    def _remove(self, name: str, chip: Gtk.Widget) -> None:
        self._selected = [s for s in self._selected if s[1].lower() != name.lower()]
        self._chips_box.remove(chip)

    def resolve_ids(self) -> list[str]:
        out: list[str] = []
        for tid, name in self._selected:
            if tid is None:
                tid = _create_tag(name)
            if tid:
                out.append(tid)
        return out


# ── Description row ─────────────────────────────────────────────────────────


class _DescriptionRow(Adw.PreferencesRow):
    def __init__(self) -> None:
        super().__init__()
        self.set_activatable(False)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.set_margin_top(10)
        outer.set_margin_bottom(10)
        outer.set_margin_start(12)
        outer.set_margin_end(12)
        lbl = Gtk.Label(label="Description", xalign=0.0)
        lbl.add_css_class("dim-label")
        outer.append(lbl)

        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(110)
        scroll.add_css_class("card")
        self._view = Gtk.TextView()
        self._view.set_wrap_mode(Gtk.WrapMode.WORD)
        self._view.set_top_margin(8)
        self._view.set_bottom_margin(8)
        self._view.set_left_margin(10)
        self._view.set_right_margin(10)
        scroll.set_child(self._view)
        outer.append(scroll)
        self.set_child(outer)

    def value(self) -> str:
        buf = self._view.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True).strip()


# ── Main window ─────────────────────────────────────────────────────────────


class TaskFormWindow(Adw.ApplicationWindow):
    def __init__(
        self,
        app: Adw.Application,
        initial_date: date | None = None,
        on_created: Callable[[dict], None] | None = None,
    ) -> None:
        super().__init__(application=app, title="New task")
        self.set_default_size(480, 760)
        self._on_created = on_created

        # Top-level layout: ToastOverlay → Box (header + content scroll).
        overlay = Adw.ToastOverlay()
        self._overlay = overlay
        self.set_content(overlay)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        overlay.set_child(root)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        self._add_btn = Gtk.Button(label="Add", css_classes=["suggested-action"])
        self._add_btn.connect("clicked", lambda _b: self._submit())
        header.pack_end(self._add_btn)
        root.append(header)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_propagate_natural_height(True)
        clamp = Adw.Clamp(maximum_size=540, tightening_threshold=480)
        page = Adw.PreferencesPage()
        clamp.set_child(page)
        scroll.set_child(clamp)
        root.append(scroll)

        # ── Group: Basic ──────────────────────────────────────────
        basic = Adw.PreferencesGroup(title="Task")
        page.add(basic)
        self._title = Adw.EntryRow(title="Title")
        self._title.set_show_apply_button(False)
        self._title.connect("entry-activated", lambda _r: self._submit())
        basic.add(self._title)

        self._project = Adw.ComboRow(title="Project")
        self._project_store = Gtk.StringList.new(["📥 Inbox (no project)"])
        self._project.set_model(self._project_store)
        self._project_ids: list[str | None] = [None]
        basic.add(self._project)

        # ── Group: When ───────────────────────────────────────────
        when = Adw.PreferencesGroup(title="When")
        page.add(when)
        self._sched = _DateTimeRow("Scheduled", initial_date=initial_date)
        when.add(self._sched)
        self._dl = _DateTimeRow("Deadline")
        when.add(self._dl)

        # ── Group: Priority & flags ──────────────────────────────
        flags = Adw.PreferencesGroup(title="Priority & flags")
        page.add(flags)
        self._priority = _PriorityRow()
        flags.add(self._priority)
        self._important = Adw.SwitchRow(title="Important", subtitle="Eisenhower: top half")
        flags.add(self._important)
        self._urgent = Adw.SwitchRow(title="Urgent", subtitle="Eisenhower: right half")
        flags.add(self._urgent)

        # ── Group: Tags ──────────────────────────────────────────
        self._tags_group = Adw.PreferencesGroup(title="Tags")
        page.add(self._tags_group)
        self._tags_row: _TagsRow | None = None

        # ── Group: Other ─────────────────────────────────────────
        other = Adw.PreferencesGroup(title="Other")
        page.add(other)
        adj = Gtk.Adjustment(value=0, lower=0, upper=720, step_increment=5)
        self._estimate = Adw.SpinRow(title="Estimate (min)", adjustment=adj, digits=0)
        other.add(self._estimate)

        self._description = _DescriptionRow()
        other.add(self._description)

        # ── Wiring ────────────────────────────────────────────────
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)

        # ``select_region`` works around the row's default behavior of
        # not auto-focusing the inner entry; we force focus on the inner
        # editable so typing starts immediately.
        GLib.idle_add(self._title.grab_focus)
        self._load_dropdowns()

    # ── Async loading ──────────────────────────────────────────────

    def _load_dropdowns(self) -> None:
        def worker() -> None:
            try:
                projects, tags = _fetch_projects_and_tags()
            except Exception as e:  # noqa: BLE001
                GLib.idle_add(toast, "Load failed", str(e), True)
                return
            GLib.idle_add(self._populate, projects, tags)

        threading.Thread(target=worker, daemon=True).start()

    def _populate(
        self, projects: dict[str, str], tags: list[dict[str, Any]]
    ) -> bool:
        for pid, pname in sorted(projects.items(), key=lambda kv: kv[1].lower()):
            self._project_store.append(f"#{pname}")
            self._project_ids.append(pid)
        self._tags_row = _TagsRow(tags)
        self._tags_group.add(self._tags_row)
        return False

    # ── Submit / payload ───────────────────────────────────────────

    def _build_payload(self) -> tuple[dict[str, Any] | None, str]:
        title = self._title.get_text().strip()
        if not title:
            return None, "Title is required."
        payload: dict[str, Any] = {"title": title}

        idx = self._project.get_selected()
        if 0 <= idx < len(self._project_ids):
            pid = self._project_ids[idx]
            if pid:
                payload["project_id"] = pid

        sched_d = self._sched.date_value()
        sched_t = self._sched.time_value()
        if sched_t and not sched_d:
            return None, "Scheduled time set without a scheduled date."
        if sched_d:
            payload["scheduled_date"] = sched_d.isoformat()
        if sched_t:
            payload["fixed_start_time"] = f"{sched_t[0]:02d}:{sched_t[1]:02d}:00"

        dl_d = self._dl.date_value()
        dl_t = self._dl.time_value()
        if dl_d:
            h, m = dl_t if dl_t else (23, 59)
            local = datetime(dl_d.year, dl_d.month, dl_d.day, h, m)
            payload["deadline"] = (
                local.astimezone(UTC).isoformat().replace("+00:00", "Z")
            )

        pri = self._priority.value()
        if pri > 0:
            payload["priority"] = pri
        if self._important.get_active():
            payload["is_important"] = True
        if self._urgent.get_active():
            payload["is_urgent"] = True

        est = int(self._estimate.get_value())
        if est > 0:
            payload["estimated_minutes"] = est

        desc = self._description.value()
        if desc:
            payload["description"] = desc

        return payload, ""

    def _submit(self) -> None:
        payload, err = self._build_payload()
        if err:
            self._show_toast(err)
            return
        assert payload is not None
        tags_row = self._tags_row

        def worker() -> None:
            try:
                if tags_row is not None:
                    tag_ids = tags_row.resolve_ids()
                    if tag_ids:
                        payload["tag_ids"] = tag_ids
                created, err = _post_task(payload)
            except Exception as e:  # noqa: BLE001
                GLib.idle_add(self._on_failed, str(e))
                return
            if created is None:
                GLib.idle_add(self._on_failed, err)
                return
            GLib.idle_add(self._on_done, created)

        self._add_btn.set_sensitive(False)
        threading.Thread(target=worker, daemon=True).start()

    def _on_done(self, created: dict) -> bool:
        wake_fetcher()
        if self._on_created:
            self._on_created(created)
        toast("Task added", created.get("title", ""))
        self.close()
        return False

    def _on_failed(self, err: str) -> bool:
        self._add_btn.set_sensitive(True)
        self._show_toast(err)
        return False

    def _show_toast(self, body: str) -> None:
        t = Adw.Toast.new(body)
        t.set_timeout(4)
        self._overlay.add_toast(t)

    def _on_key(self, _ctrl, keyval, _kc, _mods) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False


# ── App entrypoint ──────────────────────────────────────────────────────────


class _FormApp(Adw.Application):
    def __init__(
        self,
        initial_date: date | None = None,
        on_created: Callable[[dict], None] | None = None,
    ) -> None:
        super().__init__(application_id="org.wayland-conky.TaskForm")
        self._initial_date = initial_date
        self._on_created = on_created

    def do_activate(self) -> None:
        apply_theme()
        win = TaskFormWindow(
            self, initial_date=self._initial_date, on_created=self._on_created
        )
        win.present()


def show(
    initial_date: date | None = None,
    on_created: Callable[[dict], None] | None = None,
) -> int:
    app = _FormApp(initial_date=initial_date, on_created=on_created)
    return app.run(None) or 0
