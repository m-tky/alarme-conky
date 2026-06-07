"""Fuzzy-pick any task and open it in the Flutter app.

The app may not have registered the ``task-app://`` URI scheme yet, so
the clipboard fallback writes a human-readable ``"Title — UUID"`` line
instead of a raw id — pasting that into the search box of the Flutter
app finds the task either by title or by id.
"""

from __future__ import annotations

import argparse
import subprocess
from typing import Any

from .shared.format import fetch_project_map, fmt_task_label
from .shared.fuzzel import CancelledByUser, pick
from .shared.http import client
from .shared.notify import toast


def _open_or_copy(task: dict[str, Any]) -> None:
    task_id = str(task["id"])
    title = task.get("title") or "(no title)"
    try:
        rc = subprocess.run(
            ["xdg-open", f"task-app://task/{task_id}"],
            check=False,
            timeout=3,
        ).returncode
        if rc == 0:
            return
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    # Clipboard fallback: write something paste-search friendly.
    payload = f"{title} — {task_id}"
    try:
        subprocess.run(
            ["wl-copy"], input=payload.encode(), check=False, timeout=3
        )
        toast("Copied", payload)
    except (FileNotFoundError, subprocess.SubprocessError):
        toast("Jump", f"Couldn't open or copy: {task_id}", urgent=True)


def main(_args: argparse.Namespace) -> int:
    with client() as c:
        r = c.get("/api/v1/tasks", params={"limit": 500})
        if r.status_code != 200:
            toast("Jump failed", f"list: {r.status_code}", urgent=True)
            return 1
        body = r.json()
        items: list[dict[str, Any]] = (
            body.get("data") if isinstance(body, dict) else body
        ) or []
        if not items:
            toast("Jump", "No tasks.")
            return 0
        proj = fetch_project_map(c)
        choices: list[tuple[str, dict[str, Any]]] = [
            (
                fmt_task_label(
                    t,
                    project_name=proj.get(t.get("project_id")),
                    show_status_glyph=True,
                ),
                t,
            )
            for t in items
            if isinstance(t, dict)
        ]
        try:
            task = pick("Jump to", choices)
        except CancelledByUser:
            return 0
    _open_or_copy(task)
    return 0


def add_args(_p: argparse.ArgumentParser) -> None:
    pass
