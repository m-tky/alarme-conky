"""Toggle / set today's count on a picked habit.

For habits with ``target_count == 1`` this is a one-tap flip
(checked ↔ unchecked). For habits with a higher target_count, the
user gets a second prompt to enter the new total (e.g. "drink water
3 times" can record 1, 2, or 3 cups for the day).
"""

from __future__ import annotations

import argparse
from datetime import date
from typing import Any

from .shared.fetcher_signal import wake_fetcher
from .shared.format import parse_validation_error
from .shared.fuzzel import CancelledByUser, pick
from .shared.http import client
from .shared.notify import toast


def _today_count(habit: dict) -> int:
    """How many checks today, summed across log rows for safety."""
    n = 0
    for log in habit.get("logs") or []:
        if isinstance(log, dict):
            n += int(log.get("count") or 0)
    return n


def _label(h: dict) -> str:
    target = int(h.get("target_count") or 1)
    n = _today_count(h)
    if target == 1:
        glyph = "✓" if n > 0 else "○"
        return f"{glyph} {h.get('name','(unnamed)')}"
    return f"{n}/{target}  {h.get('name','(unnamed)')}"


def _ask_new_count(h: dict) -> int | None:
    target = int(h.get("target_count") or 1)
    if target == 1:
        # Simple toggle — no second prompt needed.
        return 0 if _today_count(h) > 0 else 1

    # target_count > 1 — let the user pick the new total.
    current = _today_count(h)
    choices = [
        (f"{i} of {target}", i) for i in range(target + 1)
    ]
    # Move "current+1" first so just-Enter advances the streak.
    if current < target:
        nxt = current + 1
        choices = [(f"{nxt} of {target}  (next)", nxt)] + [
            c for c in choices if c[1] != nxt
        ]
    try:
        return pick(f"{h.get('name','')} today", choices)
    except CancelledByUser:
        return None


def main(_args: argparse.Namespace) -> int:
    with client() as c:
        r = c.get("/api/v1/habits/today")
        if r.status_code != 200:
            toast("Habit list failed", f"{r.status_code}", urgent=True)
            return 1
        items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        if not items:
            toast("Habits", "No habits configured.")
            return 0
        choices = [(_label(h), h) for h in items if isinstance(h, dict)]
        try:
            h = pick("Habit", choices)
        except CancelledByUser:
            return 0
        new_count = _ask_new_count(h)
        if new_count is None:
            return 0

        today = date.today().isoformat()
        resp = c.put(
            f"/api/v1/habits/{h['id']}/logs",
            json={"date": today, "count": new_count},
        )
        if resp.status_code not in (200, 201, 204):
            toast(
                "Habit failed",
                parse_validation_error(resp.status_code, resp.text),
                urgent=True,
            )
            return 1

    wake_fetcher()
    target = int(h.get("target_count") or 1)
    name = h.get("name", "")
    if target == 1:
        toast("Habit", f"{name}  ·  {'✓' if new_count else '○'}")
    else:
        toast("Habit", f"{name}  ·  {new_count}/{target}")
    return 0


def add_args(_p: argparse.ArgumentParser) -> None:
    pass
