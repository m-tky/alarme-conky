"""Top-level command palette: one fuzzel prompt that fans out to every
other subcommand. Decorated with live context from the fetcher's
state.json so the user sees current state without opening the conky
panel — "Pomodoro running 18m left", "Inbox: 5 items", etc.
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
        today_marker = f"{today_n} today  ·  ⚠ {overdue} overdue"

    return {
        "add": "",
        "add_g": "",
        "done": today_marker,
        "delete": "",
        "snooze": today_marker,
        "pomo": pomo_label,
        "habit": "",
        "jump": "",
        "cal": "",
        "toggle": "",
        "inbox": f"{inbox_n} items",
        "done_today": f"{done_today_n} completed",
    }


def main(_args: argparse.Namespace) -> int:
    ctx = _context_suffix()

    def row(emoji: str, name: str, key: str, payload):
        suffix = ctx.get(key) or ""
        label = f"{emoji} {name}"
        if suffix:
            label = f"{label}  ·  {suffix}"
        return (label, (key, payload))

    choices = [
        row("➕", "Add task",          "add",        False),
        row("➕", "Add task (guided)", "add_g",      True),
        row("✓",  "Mark done",         "done",       None),
        row("✗",  "Delete task",       "delete",     None),
        row("⏰", "Snooze",             "snooze",     None),
        row("🍅", "Pomodoro",           "pomo",       None),
        row("✔",  "Habit check",       "habit",      None),
        row("🔍", "Jump to task",      "jump",       None),
        row("📅", "Calendar",          "cal",        None),
        row("🪟", "Toggle conky",      "toggle",     None),
    ]
    try:
        picked = pick("Task", choices)
    except CancelledByUser:
        return 0
    kind, payload = picked
    ns = argparse.Namespace()
    if kind in ("add", "add_g"):
        ns.guided = bool(payload)
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
