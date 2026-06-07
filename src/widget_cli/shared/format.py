"""Shared formatting helpers: task row labels, error parsing, state read.

These exist so every subcommand surfaces the same information in the
same shape — when the user sees a fuzzel list of tasks in `done` and
later in `snooze`, the rows look identical and they don't have to
re-learn the columns.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from .config import STATE_PATH


# ── Pick-list row formatting ─────────────────────────────────────────────────


def fmt_task_label(
    task: dict[str, Any],
    project_name: str | None = None,
    *,
    show_status_glyph: bool = False,
) -> str:
    """Build a human-readable row for fuzzel listings.

    Columns (each optional, separated by two spaces so fuzzel's
    substring matching doesn't get confused):

      [glyph]  [HH:MM]  title  [#project]  [⚠ deadline]  [★]  [!]

    The glyph column is opt-in because a `pick` list of homogeneous
    rows (e.g. "today's tasks") looks cleaner without one, while a
    mixed-status list (e.g. jump) benefits from the visual hint.
    """
    parts: list[str] = []
    status = task.get("status")
    if show_status_glyph:
        parts.append(
            {"done": "✓", "doing": "◐", "not_yet": "○", "cancelled": "✗"}.get(
                status, "·"
            )
        )

    time_part = (task.get("fixed_start_time") or "")[:5]
    if time_part:
        parts.append(time_part)

    parts.append(task.get("title") or "(no title)")

    if project_name:
        parts.append(f"#{project_name}")

    raw_dl = task.get("deadline")
    if raw_dl:
        today = date.today().isoformat()
        d = raw_dl[:10]
        marker = "⚠" if d <= today else "→"
        # Show MM-DD only when the year matches the user's current year,
        # otherwise full YYYY-MM-DD so cross-year deadlines don't lie.
        same_year = d.startswith(today[:4])
        parts.append(f"{marker} {d[5:] if same_year else d}")

    if task.get("is_important"):
        parts.append("★")
    if task.get("is_urgent"):
        parts.append("!")

    return "  ".join(parts)


# ── Pydantic / FastAPI error parsing ─────────────────────────────────────────


def parse_validation_error(status_code: int, body: str | dict) -> str:
    """Turn a 4xx response body into a one-line, human-readable summary.

    Handles three shapes we see in the wild:
      1. FastAPI built-in 422: ``{"detail":[{"loc":[...], "msg":"..."}]}``
      2. The task project's structured error:
         ``{"error":{"code":"...", "message":"...", "fields":{...}}}``
      3. Anything else: fall back to truncating the raw text.
    """
    payload: dict | None
    if isinstance(body, str):
        try:
            payload = json.loads(body)
        except (ValueError, TypeError):
            return f"HTTP {status_code}: {body[:120]}"
    else:
        payload = body

    # Shape (1): FastAPI 422
    if isinstance(payload, dict) and isinstance(payload.get("detail"), list):
        fields = []
        for item in payload["detail"]:
            if not isinstance(item, dict):
                continue
            loc = item.get("loc") or []
            field = ".".join(str(x) for x in loc[1:]) or "(root)"
            fields.append(f"{field}: {item.get('msg', 'invalid')}")
        if fields:
            return "  ".join(fields[:3])

    # Shape (2): task project error envelope
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        err = payload["error"]
        code = err.get("code", "")
        msg = err.get("message", "")
        # If field-level info present, prefer that
        fields = err.get("fields")
        if isinstance(fields, dict) and fields:
            return ", ".join(f"{k}: {v}" for k, v in list(fields.items())[:3])
        return f"{code}: {msg}".strip(": ")

    # Shape (3): unknown — best-effort
    return f"HTTP {status_code}: {str(payload)[:120]}"


# ── State (fetcher cache) read ───────────────────────────────────────────────


def read_state() -> dict[str, Any]:
    """Load the fetcher's most recent snapshot. Returns ``{}`` when the
    file isn't there yet (first boot, fetcher not running) so callers
    can degrade gracefully instead of crashing."""
    try:
        return json.loads(Path(STATE_PATH).read_text())
    except (FileNotFoundError, ValueError):
        return {}


# ── Project map ──────────────────────────────────────────────────────────────


def fetch_project_map(c) -> dict[str, str]:
    """Returns ``{id: name}`` for every project the caller can see.
    Used to decorate task rows with ``#project`` without a per-row
    server hit."""
    r = c.get("/api/v1/projects")
    if r.status_code != 200:
        return {}
    body = r.json()
    items = body if isinstance(body, list) else (body.get("data") or [])
    return {
        p["id"]: p["name"]
        for p in items
        if isinstance(p, dict) and p.get("id") and p.get("name")
    }
