"""Top-level command palette: one fuzzel prompt that fans out to every
other subcommand. Decorated with live context from the fetcher's
state.json so the user sees current state without opening the conky
panel — "Pomodoro running 18m left", "Inbox: 5 items", etc.

Icons are Nerd Font Font-Awesome codepoints (monotone, render in the
fuzzel font's Nerd Font fallback). Emoji like 🍅 or 📅 render in
colour on most systems, which fights the panel's monochrome palette.
"""

from __future__ import annotations

import argparse

from . import add as add_mod
from . import calendar_popup as cal_mod
from . import delete as delete_mod
from . import done as done_mod
from . import habit as habit_mod
from . import jump as jump_mod
from . import pomodoro as pomo_mod
from . import snooze as snooze_mod
from . import toggle_conky as toggle_mod
from .shared.format import read_state
from .shared.fuzzel import CancelledByUser, pick


# Nerd Font Font-Awesome glyphs (Private Use Area). Defined by
# codepoint so the file stays editor-paste safe.
_NF = {
    "plus":      "",  # Add task
    "check":     "",  # Mark done
    "trash":     "",  # Delete
    "moon":      "",  # Snooze (later)
    "stopwatch": "",  # Pomodoro
    "fire":      "",  # Habits
    "search":    "",  # Jump
    "calendar":  "",  # Calendar
    "window":    "",  # Toggle conky
    "warning":   "",  # Overdue marker in context suffix
}


def _context_suffix() -> dict[str, str]:
    """Build per-action context labels from the fetcher's snapshot."""
    st = (read_state() or {}).get("data", {})
    counters = st.get("counters") or {}
    today_n = counters.get("today") or len(st.get("today_tasks") or [])
    inbox_n = st.get("inbox_count") or len(st.get("inbox_tasks") or [])
    done_today_n = st.get("done_today_count") or 0
    pomo = st.get("pomodoro") or {}
    overdue = counters.get("overdue") or 0

    pomo_label = "Start"
    if pomo.get("remaining"):
        pomo_label = f"Stop ({pomo['remaining']} left)"

    today_marker = f"{today_n} today"
    if overdue:
        today_marker = f"{today_n} today  ·  {_NF['warning']} {overdue} overdue"

    return {
        "add": "",
        "done": today_marker,
        "delete": "",
        "snooze": today_marker,
        "pomo": pomo_label,
        "habit": "",
        "jump": "",
        "cal": "",
        "toggle": "",
    }


def main(_args: argparse.Namespace) -> int:
    ctx = _context_suffix()

    def row(glyph: str, name: str, key: str):
        suffix = ctx.get(key) or ""
        label = f"{glyph}  {name}"
        if suffix:
            label = f"{label}  ·  {suffix}"
        return (label, key)

    choices = [
        row(_NF["plus"],      "Add task",     "add"),
        row(_NF["check"],     "Mark done",    "done"),
        row(_NF["trash"],     "Delete task",  "delete"),
        row(_NF["moon"],      "Snooze",       "snooze"),
        row(_NF["stopwatch"], "Pomodoro",     "pomo"),
        row(_NF["fire"],      "Habit check",  "habit"),
        row(_NF["search"],    "Jump to task", "jump"),
        row(_NF["calendar"],  "Calendar",     "cal"),
        row(_NF["window"],    "Toggle conky", "toggle"),
    ]
    try:
        kind = pick("Task", choices)
    except CancelledByUser:
        return 0

    ns = argparse.Namespace()
    if kind == "add":
        return add_mod.main(ns)
    if kind == "done":
        return done_mod.main(ns)
    if kind == "delete":
        return delete_mod.main(ns)
    if kind == "snooze":
        return snooze_mod.main(ns)
    if kind == "pomo":
        return pomo_mod.main(ns)
    if kind == "habit":
        return habit_mod.main(ns)
    if kind == "jump":
        return jump_mod.main(ns)
    if kind == "cal":
        return cal_mod.main(ns)
    if kind == "toggle":
        return toggle_mod.main(ns)
    return 0


def add_args(_p: argparse.ArgumentParser) -> None:
    pass
