"""Delete (soft) a task picked from a fuzzel list, with a confirm step.

Backend's DELETE is logical (sets ``deleted_at``); the task can still
be restored from Trash for 30 days. We still add a confirm step because
the keybind is one chord away from `done`.
"""

from __future__ import annotations

import argparse
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


def main(_args: argparse.Namespace) -> int:
    with client() as c:
        items = _open_tasks(c)
        if not items:
            toast("Delete", "No open tasks.")
            return 0
        proj = fetch_project_map(c)
        choices = [
            (
                fmt_task_label(t, project_name=proj.get(t.get("project_id"))),
                t,
            )
            for t in items
            if isinstance(t, dict)
        ]
        try:
            task = pick("Delete", choices)
        except CancelledByUser:
            return 0

        # Confirm step — type 'y' to commit. Anything else (including
        # empty / Esc) cancels. Better to ask twice than to lose work.
        try:
            confirm = prompt(f"Delete '{task.get('title','?')}'? type y")
        except CancelledByUser:
            return 0
        if confirm.strip().lower() not in ("y", "yes"):
            toast("Delete", "Cancelled.")
            return 0

        r = c.delete(f"/api/v1/tasks/{task['id']}")
        if r.status_code not in (200, 204):
            toast(
                "Delete failed",
                parse_validation_error(r.status_code, r.text),
                urgent=True,
            )
            return 1

    wake_fetcher()
    toast("✗ Deleted", f"{task.get('title','')}  ·  Trash for 30d")
    return 0


def add_args(_p: argparse.ArgumentParser) -> None:
    pass
