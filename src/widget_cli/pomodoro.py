"""Start a Pomodoro on a picked task, or stop the active one.

UX flow:
- If a session is running: stop it (one click). Toast shows elapsed time.
- Otherwise: pick task, then pick duration (15 / 25 / 50 / custom min),
  then POST /pomodoro/start. Toast shows planned end time.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from typing import Any

from .shared.fetcher_signal import wake_fetcher
from .shared.format import fetch_project_map, fmt_task_label, parse_validation_error
from .shared.fuzzel import CancelledByUser, pick, prompt
from .shared.http import client
from .shared.notify import toast


def _open_tasks(c) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for status in ("not_yet", "doing"):
        r = c.get("/api/v1/tasks", params={"status": status, "limit": 200})
        if r.status_code != 200:
            continue
        body = r.json()
        items = body.get("data") if isinstance(body, dict) else body
        out.extend(items or [])
    return out


def _active_session(c) -> dict[str, Any] | None:
    r = c.get("/api/v1/pomodoro", params={"limit": 10})
    if r.status_code != 200:
        return None
    sessions = r.json()
    if isinstance(sessions, dict):
        sessions = sessions.get("items") or sessions.get("data") or []
    for s in sessions or []:
        if isinstance(s, dict) and not s.get("completed_at"):
            return s
    return None


def _ask_duration() -> int | None:
    choices = [
        ("25 minutes (classic)", 25),
        ("15 minutes (quick)", 15),
        ("50 minutes (deep work)", 50),
        ("custom…", -1),
    ]
    try:
        dur = pick("Duration", choices)
    except CancelledByUser:
        return None
    if dur == -1:
        try:
            raw = prompt("Minutes (1-120)")
        except CancelledByUser:
            return None
        try:
            dur = int(raw)
        except ValueError:
            toast("Pomodoro", f"Not a number: {raw}", urgent=True)
            return None
        if not (1 <= dur <= 120):
            toast("Pomodoro", f"Out of range: {dur}", urgent=True)
            return None
    return dur


def main(_args: argparse.Namespace) -> int:
    with client() as c:
        active = _active_session(c)
        if active:
            stop = c.patch(f"/api/v1/pomodoro/{active['id']}/complete", json={})
            if stop.status_code not in (200, 204):
                toast(
                    "Pomodoro stop failed",
                    parse_validation_error(stop.status_code, stop.text),
                    urgent=True,
                )
                return 1
            # Elapsed time = now - started_at for a paint-the-celebration toast.
            try:
                started = datetime.fromisoformat(
                    active["started_at"].replace("Z", "+00:00")
                )
                elapsed = datetime.now(UTC) - started
                mins = int(elapsed.total_seconds() // 60)
                toast(
                    "🍅 Stopped",
                    f"{mins}m elapsed  ·  planned {active.get('duration','?')}m",
                )
            except (KeyError, ValueError, TypeError):
                toast("🍅 Stopped", "")
            wake_fetcher()
            return 0

        items = _open_tasks(c)
        if not items:
            toast("Pomodoro", "No tasks to focus on.")
            return 0
        proj = fetch_project_map(c)
        choices = [
            (fmt_task_label(t, project_name=proj.get(t.get("project_id"))), t)
            for t in items
            if isinstance(t, dict)
        ]
        try:
            task = pick("Focus on", choices)
        except CancelledByUser:
            return 0
        duration = _ask_duration()
        if duration is None:
            return 0

        start = c.post(
            "/api/v1/pomodoro/start",
            json={"task_id": task["id"], "type": "work", "duration": duration},
        )
        if start.status_code not in (200, 201):
            toast(
                "Pomodoro start failed",
                parse_validation_error(start.status_code, start.text),
                urgent=True,
            )
            return 1

    wake_fetcher()
    ends = (datetime.now() + timedelta(minutes=duration)).strftime("%H:%M")
    toast("🍅 Focus", f"{task.get('title','')}  ·  ends {ends}")
    return 0


def add_args(_p: argparse.ArgumentParser) -> None:
    pass
