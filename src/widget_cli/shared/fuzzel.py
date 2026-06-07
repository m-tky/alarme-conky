"""Thin fuzzel wrapper.

Two modes:
- ``prompt(label)`` for free-text capture (used by the quick-add and
  for the date-text snooze fallback).
- ``pick(label, options)`` for a list selection — ``options`` is an
  iterable of ``(display, value)`` tuples, we feed ``display`` to fuzzel
  ``--dmenu`` and map the result back to the matching ``value``.

Both raise ``CancelledByUser`` on empty input / Esc so callers can
quietly exit without polluting the desktop with toast notifications.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from typing import TypeVar

T = TypeVar("T")


class CancelledByUser(Exception):
    """Raised when fuzzel exits without a selection."""


def prompt(label: str, *, password: bool = False) -> str:
    """Open fuzzel as a single-line input. Returns the typed text."""
    cmd = ["fuzzel", "--dmenu", "--prompt", f"{label}> ", "--lines", "0"]
    if password:
        cmd.append("--password")
    p = subprocess.run(cmd, input="", capture_output=True, text=True)
    out = p.stdout.strip()
    if p.returncode != 0 or not out:
        raise CancelledByUser
    return out


def pick(label: str, options: Iterable[tuple[str, T]]) -> T:
    """Pick one item. ``options`` items have a display label and an
    underlying value; the value is what the caller actually wants
    (typically a UUID or dict)."""
    rows = list(options)
    if not rows:
        raise CancelledByUser
    display = "\n".join(row[0] for row in rows)
    p = subprocess.run(
        ["fuzzel", "--dmenu", "--prompt", f"{label}> "],
        input=display,
        capture_output=True,
        text=True,
    )
    out = p.stdout.strip()
    if p.returncode != 0 or not out:
        raise CancelledByUser
    for disp, val in rows:
        if disp == out:
            return val
    # Unknown rows mean the user typed something. Bubble up so callers
    # can decide whether to treat that as input or as a cancel.
    raise CancelledByUser
