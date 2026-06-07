"""Toggle done on a today/overdue task picked from a fuzzel list.

Limited to ``today + overdue`` because that's the natural keyboard-
shortcut surface; for arbitrary completion the user can `jump` into
the Flutter app.
"""

from __future__ import annotations

import argparse
from datetime import date
from typing import Any

from .shared.fetcher_signal import wake_fetcher
from .shared.format import fetch_project_map, fmt_task_label, parse_validation_error
from .shared.fuzzel import CancelledByUser, pick
from .shared.http import client
from .shared.notify import toast


def _open_tasks(c) -> list[dict[str, Any]]:
    """Fetch every open task (not_yet + doing) in one go."""
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
    keep: list[dict[str, Any]] = []
    for t in tasks:
        sched = t.get("scheduled_date")
        raw_dl = t.get("deadline")
        deadl = raw_dl[:10] if raw_dl else None
        if sched == today or deadl == today or (deadl and deadl < today):
            keep.append(t)
    # Overdue first so they're at the top of the picker.
    keep.sort(
        key=lambda t: (
            0 if t.get("deadline", "")[:10] < today else 1,
            t.get("fixed_start_time") or "ZZ",
        )
    )
    return keep


def main(_args: argparse.Namespace) -> int:
    with client() as c:
        items = _open_tasks(c)
        candidates = _today_or_overdue(items)
        if not candidates:
            toast("Done", "Nothing on today's list.")
            return 0
        proj = fetch_project_map(c)
        choices = [
            (fmt_task_label(t, project_name=proj.get(t.get("project_id"))), t)
            for t in candidates
        ]
        try:
            task = pick("Done", choices)
        except CancelledByUser:
            return 0

        patch = c.patch(
            f"/api/v1/tasks/{task['id']}",
            json={"status": "done", "expected_version": task.get("version", 0)},
        )
        if patch.status_code not in (200, 204):
            toast(
                "Done failed",
                parse_validation_error(patch.status_code, patch.text),
                urgent=True,
            )
            return 1

        # After-state context: how much is left for the user today?
        remaining = sum(
            1
            for t in candidates
            if t["id"] != task["id"] and t.get("status") in ("not_yet", "doing")
        )

    wake_fetcher()
    body = f"{task.get('title','')}"
    if remaining > 0:
        body += f"  ·  {remaining} left today"
    else:
        body += "  ·  today's list cleared 🎉"
    toast("✓ Done", body)
    return 0


def add_args(_p: argparse.ArgumentParser) -> None:
    pass
