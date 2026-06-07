"""Push a today/overdue task into the future. Pick the task, pick the
new ``scheduled_date`` via a second prompt.

Custom date entry goes through `/parse-deadline`, so "tomorrow",
"明日", "next monday", "来週月" all work — the user shouldn't have to
remember ISO date format just because they hit a less-common branch.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
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


def _today_or_overdue(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    today = date.today().isoformat()
    out: list[dict[str, Any]] = []
    for t in tasks:
        sched = t.get("scheduled_date")
        raw_dl = t.get("deadline")
        deadl = raw_dl[:10] if raw_dl else None
        if sched == today or deadl == today or (deadl and deadl < today):
            out.append(t)
    return out


def _next_monday() -> date:
    today = date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


def _ask_when(c) -> str | None:
    today = date.today()
    choices = [
        ("Tomorrow", (today + timedelta(days=1)).isoformat()),
        ("In 2 days", (today + timedelta(days=2)).isoformat()),
        ("This Saturday", (today + timedelta(days=(5 - today.weekday()) % 7)).isoformat()),
        ("Next Monday", _next_monday().isoformat()),
        ("In 1 week", (today + timedelta(days=7)).isoformat()),
        ("type a date or phrase…", "custom"),
    ]
    try:
        pickv = pick("Snooze to", choices)
    except CancelledByUser:
        return None
    if pickv != "custom":
        return pickv
    # Custom branch: accept natural language via /parse-deadline.
    try:
        free = prompt("Date or phrase (e.g. 'next friday', '明日')")
    except CancelledByUser:
        return None
    r = c.post("/api/v1/parse-deadline", json={"text": free})
    if r.status_code != 200:
        toast("Snooze", f"Couldn't parse: {free}", urgent=True)
        return None
    return r.json().get("date_only")


def main(_args: argparse.Namespace) -> int:
    with client() as c:
        items = _open_tasks(c)
        candidates = _today_or_overdue(items)
        if not candidates:
            toast("Snooze", "Nothing on today's list.")
            return 0
        proj = fetch_project_map(c)
        choices = [
            (fmt_task_label(t, project_name=proj.get(t.get("project_id"))), t)
            for t in candidates
        ]
        try:
            task = pick("Snooze which?", choices)
        except CancelledByUser:
            return 0

        when = _ask_when(c)
        if when is None:
            return 0

        patch = c.patch(
            f"/api/v1/tasks/{task['id']}",
            json={
                "scheduled_date": when,
                "expected_version": task.get("version", 0),
            },
        )
        if patch.status_code not in (200, 204):
            toast(
                "Snooze failed",
                parse_validation_error(patch.status_code, patch.text),
                urgent=True,
            )
            return 1

    wake_fetcher()
    toast("Snoozed", f"{task.get('title','')}  →  {when}")
    return 0


def add_args(_p: argparse.ArgumentParser) -> None:
    pass
