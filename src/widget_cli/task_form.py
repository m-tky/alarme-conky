"""GTK4 task creation form — single entrypoint for all task adds.

Keyboard flow is the contract:
- Title is focused on open. Hitting Enter from Title submits immediately
  with everything else at defaults — that's the "quick capture" speed.
- Tab cycles through optional fields in declaration order, Shift+Tab
  goes back, Esc cancels.
- Date / time entries accept either a picker click or direct typing
  (YYYY-MM-DD / HH:MM) so power users never need the mouse.

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
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from .shared.fetcher_signal import wake_fetcher  # noqa: E402
from .shared.format import fetch_project_map, parse_validation_error  # noqa: E402
from .shared.http import client  # noqa: E402
from .shared.notify import toast  # noqa: E402


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
    """POST a new tag, return its id (or None on failure)."""
    with client() as c:
        r = c.post("/api/v1/tags", json={"name": name})
        if r.status_code in (200, 201):
            return r.json().get("id")
    return None


def _post_task(payload: dict[str, Any]) -> tuple[dict | None, str]:
    """Return (created_task, error_message). Exactly one is truthy."""
    with client() as c:
        r = c.post("/api/v1/tasks", json=payload)
        if r.status_code in (200, 201):
            return r.json(), ""
        return None, parse_validation_error(r.status_code, r.text)


# ── Helpers ──────────────────────────────────────────────────────────────────


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


def _format_date(d: date | None) -> str:
    return d.isoformat() if d else ""


# ── Date entry: text field + popover GtkCalendar ─────────────────────────────


class _DateField(Gtk.Box):
    def __init__(self, initial: date | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._entry = Gtk.Entry(placeholder_text="YYYY-MM-DD")
        self._entry.set_hexpand(True)
        if initial is not None:
            self._entry.set_text(_format_date(initial))
        self.append(self._entry)
        pick = Gtk.MenuButton(icon_name="x-office-calendar-symbolic")
        pop = Gtk.Popover()
        cal = Gtk.Calendar()
        if initial is not None:
            cal.select_day(GLib.DateTime.new_local(initial.year, initial.month, initial.day, 0, 0, 0))
        cal.connect("day-selected", self._on_day_selected, pop)
        pop.set_child(cal)
        pick.set_popover(pop)
        self.append(pick)
        self._cal = cal

    def _on_day_selected(self, cal: Gtk.Calendar, popover: Gtk.Popover) -> None:
        dt = cal.get_date()
        d = date(dt.get_year(), dt.get_month(), dt.get_day_of_month())
        self._entry.set_text(_format_date(d))
        popover.popdown()

    def value(self) -> date | None:
        return _parse_date(self._entry.get_text())

    def grab_focus(self) -> None:
        self._entry.grab_focus()


# ── Time entry: text field "HH:MM" ───────────────────────────────────────────


class _TimeField(Gtk.Entry):
    def __init__(self) -> None:
        super().__init__(placeholder_text="HH:MM")
        self.set_max_width_chars(6)

    def value(self) -> tuple[int, int] | None:
        return _parse_hhmm(self.get_text())

    def iso_time(self) -> str | None:
        v = self.value()
        return f"{v[0]:02d}:{v[1]:02d}:00" if v else None


# ── Priority segmented button (4 linked toggle buttons) ──────────────────────


class _PriorityField(Gtk.Box):
    """4-option linked segmented control (None / Low / Med / High)."""

    LABELS = ["None", "Low", "Med", "High"]
    VALUES = [0, 1, 2, 3]

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.add_css_class("linked")
        self._buttons: list[Gtk.ToggleButton] = []
        group: Gtk.ToggleButton | None = None
        for label, val in zip(self.LABELS, self.VALUES):
            btn = Gtk.ToggleButton(label=label)
            if group is not None:
                btn.set_group(group)
            else:
                group = btn
            if val == 0:
                btn.set_active(True)
            btn.connect("toggled", lambda *_a: None)
            self.append(btn)
            self._buttons.append(btn)

    def value(self) -> int:
        for btn, val in zip(self._buttons, self.VALUES):
            if btn.get_active():
                return val
        return 0


# ── Tag chips field ──────────────────────────────────────────────────────────


class _TagsField(Gtk.Box):
    """Entry + chip area. Hitting Enter on the entry adds a chip; the
    chip carries the tag id (existing tags) or the literal name
    (new tags resolved on submit)."""

    def __init__(self, tags: list[dict[str, Any]]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._known = {t["name"].lower(): t for t in tags if "name" in t}
        # entry + completion
        store = Gtk.StringList.new([t["name"] for t in tags if "name" in t])
        self._entry = Gtk.Entry(placeholder_text="Tag name + Enter")
        self._entry.connect("activate", self._on_activate)
        self.append(self._entry)
        self._chips_box = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            max_children_per_line=8,
            homogeneous=False,
            column_spacing=4,
            row_spacing=4,
        )
        self.append(self._chips_box)
        # entries of type tuple[id_or_None, name]
        self._selected: list[tuple[str | None, str]] = []
        _ = store  # currently unused — autocomplete added in future GTK pass

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
        chip.append(Gtk.Label(label=f"#{name}"))
        close = Gtk.Button(icon_name="window-close-symbolic")
        close.add_css_class("flat")
        close.connect("clicked", lambda _b: self._remove(name, chip))
        chip.append(close)
        self._chips_box.append(chip)

    def _remove(self, name: str, chip: Gtk.Widget) -> None:
        self._selected = [s for s in self._selected if s[1].lower() != name.lower()]
        self._chips_box.remove(chip)

    def resolve_ids(self) -> list[str]:
        """Materialise tag ids — create any chips backed by name only
        and return the full id list."""
        out: list[str] = []
        for tid, name in self._selected:
            if tid is None:
                tid = _create_tag(name)
            if tid:
                out.append(tid)
        return out


# ── Main window ──────────────────────────────────────────────────────────────


class TaskForm(Gtk.ApplicationWindow):
    def __init__(
        self,
        app: Gtk.Application,
        initial_date: date | None = None,
        on_created: Callable[[dict], None] | None = None,
    ) -> None:
        super().__init__(application=app, title="New task")
        self.set_default_size(440, 640)
        self._on_created = on_created

        outer = Gtk.ScrolledWindow()
        outer.set_propagate_natural_height(True)
        outer.set_min_content_height(560)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(14)
        box.set_margin_bottom(14)
        box.set_margin_start(14)
        box.set_margin_end(14)
        outer.set_child(box)
        self.set_child(outer)

        # ── Title (focused on open, Enter submits) ────────────────────
        self._title = Gtk.Entry(placeholder_text="Title")
        self._title.connect("activate", lambda _e: self._submit())
        box.append(self._labeled("Title", self._title))

        # ── Project dropdown ──────────────────────────────────────────
        self._project = Gtk.ComboBoxText()
        self._project.append(id="", text="📥 Inbox (no project)")
        self._project.set_active(0)
        box.append(self._labeled("Project", self._project))

        # ── Scheduled date + time ─────────────────────────────────────
        self._sched_date = _DateField(initial=initial_date)
        self._sched_time = _TimeField()
        sched_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        sched_row.append(self._sched_date)
        sched_row.append(self._sched_time)
        box.append(self._labeled("Scheduled (date + optional time)", sched_row))

        # ── Deadline date + time ──────────────────────────────────────
        self._dl_date = _DateField()
        self._dl_time = _TimeField()
        dl_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        dl_row.append(self._dl_date)
        dl_row.append(self._dl_time)
        box.append(self._labeled("Deadline (date + optional time)", dl_row))

        # ── Priority ──────────────────────────────────────────────────
        self._priority = _PriorityField()
        box.append(self._labeled("Priority", self._priority))

        # ── Flags ─────────────────────────────────────────────────────
        flag_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self._important = Gtk.CheckButton(label="★ Important")
        self._urgent = Gtk.CheckButton(label="! Urgent")
        flag_row.append(self._important)
        flag_row.append(self._urgent)
        box.append(flag_row)

        # ── Tags (populated when fetch completes) ─────────────────────
        self._tags: _TagsField | None = None
        self._tags_slot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(self._labeled("Tags", self._tags_slot))

        # ── Estimate ──────────────────────────────────────────────────
        adj = Gtk.Adjustment(value=0, lower=0, upper=720, step_increment=5)
        self._estimate = Gtk.SpinButton(adjustment=adj, digits=0)
        self._estimate.set_numeric(True)
        self._estimate.set_max_width_chars(6)
        est_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        est_row.append(self._estimate)
        est_row.append(Gtk.Label(label="min"))
        box.append(self._labeled("Estimate", est_row))

        # ── Description (multi-line) ─────────────────────────────────
        self._desc = Gtk.TextView()
        self._desc.set_wrap_mode(Gtk.WrapMode.WORD)
        self._desc.set_size_request(-1, 100)
        desc_scroll = Gtk.ScrolledWindow()
        desc_scroll.set_min_content_height(100)
        desc_scroll.set_child(self._desc)
        box.append(self._labeled("Description", desc_scroll))

        # ── Buttons ───────────────────────────────────────────────────
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_halign(Gtk.Align.END)
        self._cancel_btn = Gtk.Button(label="Cancel")
        self._cancel_btn.connect("clicked", lambda _b: self.close())
        self._add_btn = Gtk.Button(label="Add", css_classes=["suggested-action"])
        self._add_btn.connect("clicked", lambda _b: self._submit())
        actions.append(self._cancel_btn)
        actions.append(self._add_btn)
        box.append(actions)

        # Esc to cancel.
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)

        self._title.grab_focus()
        self._load_dropdowns()

    # ── helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _labeled(label: str, child: Gtk.Widget) -> Gtk.Box:
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        lbl = Gtk.Label(xalign=0.0, label=label)
        lbl.add_css_class("dim-label")
        b.append(lbl)
        b.append(child)
        return b

    def _on_key(self, _ctrl, keyval, _kc, _mods) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    # ── Async data load ────────────────────────────────────────────────

    def _load_dropdowns(self) -> None:
        def worker() -> None:
            try:
                projects, tags = _fetch_projects_and_tags()
            except Exception as e:  # noqa: BLE001
                GLib.idle_add(toast, "Load failed", str(e), True)
                return
            GLib.idle_add(self._populate_dropdowns, projects, tags)

        threading.Thread(target=worker, daemon=True).start()

    def _populate_dropdowns(
        self, projects: dict[str, str], tags: list[dict[str, Any]]
    ) -> bool:
        for pid, pname in sorted(projects.items(), key=lambda kv: kv[1].lower()):
            self._project.append(id=pid, text=f"#{pname}")
        self._tags = _TagsField(tags)
        self._tags_slot.append(self._tags)
        return False

    # ── Submit ─────────────────────────────────────────────────────────

    def _build_payload(self) -> tuple[dict[str, Any] | None, str]:
        """Validate and assemble. Returns (payload, error_message)."""
        title = self._title.get_text().strip()
        if not title:
            return None, "Title is required."
        payload: dict[str, Any] = {"title": title}

        pid = self._project.get_active_id()
        if pid:
            payload["project_id"] = pid

        sched_d = self._sched_date.value()
        sched_t = self._sched_time.iso_time()
        if sched_t and not sched_d:
            return None, "Scheduled time set but no scheduled date."
        if sched_d:
            payload["scheduled_date"] = sched_d.isoformat()
        if sched_t:
            payload["fixed_start_time"] = sched_t

        dl_d = self._dl_date.value()
        dl_t = self._dl_time.value()
        if dl_d:
            h, m = dl_t if dl_t else (23, 59)
            # Local time → UTC ISO 8601. The backend stores TIMESTAMPTZ.
            local = datetime(dl_d.year, dl_d.month, dl_d.day, h, m)
            payload["deadline"] = (
                local.astimezone(UTC).isoformat().replace("+00:00", "Z")
            )

        prio = self._priority.value()
        if prio > 0:
            payload["priority"] = prio
        if self._important.get_active():
            payload["is_important"] = True
        if self._urgent.get_active():
            payload["is_urgent"] = True

        est = int(self._estimate.get_value())
        if est > 0:
            payload["estimated_minutes"] = est

        buf = self._desc.get_buffer()
        desc = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True).strip()
        if desc:
            payload["description"] = desc

        return payload, ""

    def _submit(self) -> None:
        payload, err = self._build_payload()
        if err:
            toast("Add failed", err, urgent=True)
            return
        assert payload is not None
        # Tag id materialisation can hit the network — keep it off the
        # GTK main loop so the form stays responsive while creating
        # new tags.
        tags_field = self._tags

        def worker() -> None:
            try:
                if tags_field is not None:
                    tag_ids = tags_field.resolve_ids()
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
        toast("Add failed", err, urgent=True)
        return False


# ── Application entrypoint ───────────────────────────────────────────────────


class _FormApp(Gtk.Application):
    def __init__(
        self,
        initial_date: date | None = None,
        on_created: Callable[[dict], None] | None = None,
    ) -> None:
        super().__init__(application_id="org.wayland-conky.TaskForm")
        self._initial_date = initial_date
        self._on_created = on_created

    def do_activate(self) -> None:
        win = TaskForm(
            self, initial_date=self._initial_date, on_created=self._on_created
        )
        win.present()


def show(
    initial_date: date | None = None,
    on_created: Callable[[dict], None] | None = None,
) -> int:
    """Open the form and block until the window closes. Used both as
    a CLI subcommand entrypoint and from the calendar popup."""
    app = _FormApp(initial_date=initial_date, on_created=on_created)
    return app.run(None) or 0
