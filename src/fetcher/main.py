#!/usr/bin/env python3
"""Background fetcher for wayland-conky.

Runs as a systemd user service. Every ``poll_seconds`` it pulls the
data the panel needs (counters, today's tasks, habits, pomodoro,
calendar, notes) over the existing task API, normalises them, and
writes a single JSON snapshot to ``~/.cache/wayland-conky/state.json``.
Conky reads that file with ``jq`` — see ``modules/home.nix``.

Why a daemon and not many ``execi`` blocks: each block would do its
own HTTP handshake against orangepi over Tailscale. One asyncio
client multiplexes them inside a single keepalive connection, so the
panel feels instant after a mutation: ``widget-cli`` sends SIGUSR1
and the next iteration fires within milliseconds.

Failure handling: on any HTTP/network error we *keep* the last good
``data`` block and just stamp ``meta.last_error``. The panel paints
an age badge from ``meta.fetched_at_epoch`` so the user can tell
they're looking at stale numbers; ``notify-send`` toasts the error
once per 10 minutes per kind so the desktop stays quiet.
"""

from __future__ import annotations

import asyncio
import calendar as calendar_mod
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

# ── Paths ─────────────────────────────────────────────────────────────────────

XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
XDG_CACHE = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))

CONFIG_PATH = XDG_CONFIG / "wayland-conky" / "config.toml"
TOKEN_PATH = XDG_CONFIG / "wayland-conky" / "token"
STATE_PATH = XDG_CACHE / "wayland-conky" / "state.json"
NOTIF_COOLDOWN_PATH = XDG_CACHE / "wayland-conky" / "notif-cooldown.json"

NOTIF_COOLDOWN_SECONDS = 600  # 10 minutes per error kind

log = logging.getLogger("wayland-conky-fetcher")


# ── Config & token loading ────────────────────────────────────────────────────


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        # Fall back to env-only defaults so the first systemd boot before
        # ``wayland-conky setup`` ran still produces a non-crashing daemon.
        return {
            "api_base_url": "http://localhost:8001",
            "poll_seconds": 30,
        }
    with CONFIG_PATH.open("rb") as f:
        return tomllib.load(f)


def load_token() -> str | None:
    if not TOKEN_PATH.exists():
        return None
    return TOKEN_PATH.read_text().strip() or None


# ── Atomic state write ────────────────────────────────────────────────────────


def write_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # ``os.replace`` is atomic on POSIX — conky never reads a half-written
    # file because we hand it the inode swap.
    fd, tmp = tempfile.mkstemp(
        prefix=".state.", suffix=".json", dir=STATE_PATH.parent
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, STATE_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── Notification cooldown ─────────────────────────────────────────────────────


def _load_cooldown() -> dict[str, float]:
    if not NOTIF_COOLDOWN_PATH.exists():
        return {}
    try:
        return json.loads(NOTIF_COOLDOWN_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cooldown(d: dict[str, float]) -> None:
    NOTIF_COOLDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
    NOTIF_COOLDOWN_PATH.write_text(json.dumps(d))


def notify(kind: str, summary: str, body: str) -> None:
    """Show a desktop notification, but at most once per ``kind`` per
    cooldown window. The kind is what gates throttling, not the body —
    so the user sees "connection refused" once even if it repeats."""
    now = time.time()
    cd = _load_cooldown()
    last = cd.get(kind, 0.0)
    if now - last < NOTIF_COOLDOWN_SECONDS:
        return
    cd[kind] = now
    _save_cooldown(cd)
    try:
        subprocess.run(
            ["notify-send", "-a", "wayland-conky", "-u", "normal", summary, body],
            check=False,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as e:
        log.warning("notify-send failed: %s", e)


# ── Fetch helpers ─────────────────────────────────────────────────────────────


def _today_iso() -> str:
    return date.today().isoformat()


def _end_of_week_iso() -> str:
    today = date.today()
    return (today + timedelta(days=(6 - today.weekday()))).isoformat()


async def fetch_all(client: httpx.AsyncClient) -> dict[str, Any]:
    """Hit every endpoint we need and normalise into the snapshot the
    conkyrc reads. Endpoints are intentionally tolerant of failure —
    if one path 404s on an older backend, the rest still populate."""
    today = _today_iso()
    end_week = _end_of_week_iso()

    async def get(path: str, **params) -> Any:
        r = await client.get(path, params=params)
        r.raise_for_status()
        return r.json()

    # Run as many as we can in parallel — the orangepi can take it,
    # and panel paint feels snappier when the whole snapshot lands together.
    # Task `status` enum is {not_yet, doing, done, cancelled}; we fetch
    # both "open" statuses (not_yet + doing) because anything Inbox or
    # Today candidates should include in-progress work too.
    # No /pomodoro/current endpoint: list and filter for the one without
    # completed_at. Notes have no global listing — task/project-scoped
    # only, so the block stays blank for now.
    results = await asyncio.gather(
        get("/api/v1/tasks", status="not_yet", limit=200),
        get("/api/v1/tasks", status="doing", limit=50),
        # Recently-done tasks for the "Done today" celebration block.
        # We over-fetch slightly and filter client-side on the date
        # portion of ``updated_at`` because the backend doesn't have
        # a "done since" filter.
        get("/api/v1/tasks", status="done", limit=30),
        get("/api/v1/habits/today"),
        get("/api/v1/pomodoro", limit=5),
        return_exceptions=True,
    )

    tasks_raw, tasks_doing_raw, tasks_done_raw, habits_raw, pomodoro_raw = results
    notes_raw = []

    # ── Tasks → counters + today + inbox + calendar ───────────────────────
    # The task backend has no separate event/calendar table. The Flutter
    # Calendar tab is built from tasks with a deadline; the TaskChute
    # "Today" timeline is scheduled_date == today OR deadline == today.
    # The panel echoes those rules and adds an Inbox block for triage of
    # unscheduled work — anything with neither scheduled_date nor
    # deadline is candidate for "what should I plan next?"
    counters = {"overdue": 0, "today": 0, "this_week": 0}
    today_tasks: list[dict[str, Any]] = []
    inbox_tasks: list[dict[str, Any]] = []
    inbox_count = 0
    calendar_upcoming: list[dict[str, Any]] = []
    # Per-day count of *future* days in the current month with either a
    # scheduled_date OR a deadline. Past days are left uncoloured even
    # if something landed there — markers answer "where's my next gap?",
    # not "where have I been?".
    busy_counts: dict[int, int] = {}
    today_dt = date.today()
    items: list[dict[str, Any]] = []
    # /tasks returns TaskListResponse{ data, next_cursor, has_more }.
    # The earlier `.items` / `.tasks` keys never matched, which is why
    # every counter rendered as zero against a healthy backend.
    for raw in (tasks_raw, tasks_doing_raw):
        if isinstance(raw, dict):
            items.extend(raw.get("data") or [])
        elif isinstance(raw, list):
            items.extend(raw)
    for t in items:
        if not isinstance(t, dict):
            continue
        # deadline arrives as ISO 8601 datetime (TZ-aware); scheduled_date
        # is plain YYYY-MM-DD. Trim deadline to date for date-vs-date
        # comparisons; the time-of-day part isn't relevant to "is it
        # overdue?" or "is it due today?" for our display.
        raw_deadline = t.get("deadline")
        deadline_date = raw_deadline[:10] if raw_deadline else None
        scheduled = t.get("scheduled_date")
        time_part = (t.get("fixed_start_time") or "")[:5]
        if deadline_date and deadline_date < today:
            counters["overdue"] += 1
        if scheduled == today or deadline_date == today:
            counters["today"] += 1
            today_tasks.append(
                {
                    "id": t.get("id"),
                    "title": t.get("title", "")[:48],
                    "scheduled_time": time_part or None,
                }
            )
        # "This week" = scheduled in [today, end_of_week]. Deadline-only
        # tasks aren't counted here — Calendar/Overdue already cover them.
        if scheduled and today <= scheduled <= end_week:
            counters["this_week"] += 1
        # Upcoming highlights surface the next 1-2 specific items so the
        # user gets concrete context alongside the grid.
        if scheduled and today < scheduled <= end_week:
            when = scheduled[5:]
            if time_part:
                when = f"{when} {time_part}"
            calendar_upcoming.append(
                {"title": (t.get("title") or "")[:32], "when": when}
            )
        # Inbox: nothing scheduled, nothing deadlined. Pure "needs
        # triage" candidates. Cap at 3 visible + a remainder counter.
        if scheduled is None and deadline_date is None:
            inbox_count += 1
            if len(inbox_tasks) < 3:
                inbox_tasks.append(
                    {
                        "id": t.get("id"),
                        "title": (t.get("title") or "")[:48],
                    }
                )
        # Grid busy markers consider *either* scheduled_date or deadline
        # so a task with only a deadline shows up next to days that have
        # explicit timeline entries.
        for raw_d in (scheduled, deadline_date):
            if not raw_d:
                continue
            try:
                d = date.fromisoformat(raw_d)
            except ValueError:
                continue
            if (
                d >= today_dt
                and d.year == today_dt.year
                and d.month == today_dt.month
            ):
                busy_counts[d.day] = busy_counts.get(d.day, 0) + 1
    calendar_upcoming.sort(key=lambda c: c["when"])
    calendar_upcoming = calendar_upcoming[:5]
    calendar_grid = _render_month_grid(today_dt, busy_counts)
    calendar_highlights = [
        f"→ {c['when']}  {c['title']}" for c in calendar_upcoming[:2]
    ]

    # ── Done today (proxy: status=done AND updated_at[:10] == today) ─────
    done_items: list[dict[str, Any]] = []
    if isinstance(tasks_done_raw, dict):
        done_items = tasks_done_raw.get("data") or []
    elif isinstance(tasks_done_raw, list):
        done_items = tasks_done_raw
    done_today_tasks: list[dict[str, Any]] = []
    for t in done_items:
        if not isinstance(t, dict):
            continue
        upd = (t.get("updated_at") or "")[:10]
        if upd == today:
            done_today_tasks.append({"title": (t.get("title") or "")[:48]})
    done_today_count = len(done_today_tasks)

    # ── Habits today ──────────────────────────────────────────────────────
    # /habits/today returns HabitOut rows whose `logs` array is exactly
    # today's logs for that habit; non-empty + count > 0 ⇒ checked.
    habits_today: list[dict[str, Any]] = []
    if not isinstance(habits_raw, Exception):
        items = habits_raw if isinstance(habits_raw, list) else habits_raw.get("items", [])
        for h in items[:8]:
            if not isinstance(h, dict):
                continue
            logs = h.get("logs") or []
            done = any(isinstance(l, dict) and (l.get("count") or 0) > 0 for l in logs)
            habits_today.append({"name": h.get("name", "")[:12], "done": done})

    # ── Pomodoro current ──────────────────────────────────────────────────
    # No dedicated "active session" endpoint; the recent-sessions list is
    # the source of truth. An active row has no completed_at and its
    # started_at + duration is still in the future.
    pomodoro: dict[str, Any] | None = None
    if not isinstance(pomodoro_raw, Exception) and pomodoro_raw:
        sessions = pomodoro_raw if isinstance(pomodoro_raw, list) else pomodoro_raw.get("items", [])
        now = datetime.now(UTC)
        for sess in sessions:
            if not isinstance(sess, dict) or sess.get("completed_at"):
                continue
            try:
                started = datetime.fromisoformat(
                    sess["started_at"].replace("Z", "+00:00")
                )
                # Backend's `duration` is in minutes.
                duration_s = int(sess.get("duration") or 25) * 60
                remaining = duration_s - int((now - started).total_seconds())
                if remaining > 0:
                    pomodoro = {
                        "task_title": "Focus",
                        "remaining": f"{remaining // 60:02d}:{remaining % 60:02d}",
                    }
                    break
            except (ValueError, KeyError, TypeError):
                continue

    # ── Notes recent ──────────────────────────────────────────────────────
    notes_recent: list[dict[str, Any]] = []
    if not isinstance(notes_raw, Exception):
        items = notes_raw if isinstance(notes_raw, list) else notes_raw.get("items", [])
        for n in items[:3]:
            if isinstance(n, dict):
                notes_recent.append({"title": (n.get("title") or "Untitled")[:40]})

    return {
        "counters": counters,
        "today_tasks": today_tasks[:5],
        "done_today_tasks": done_today_tasks[:5],
        "done_today_count": done_today_count,
        "inbox_tasks": inbox_tasks,
        "inbox_count": inbox_count,
        "habits_today": habits_today,
        "pomodoro": pomodoro,
        "notes_recent": notes_recent,
        "calendar_upcoming": calendar_upcoming,
        "calendar_grid": calendar_grid,
        "calendar_highlights": calendar_highlights,
    }


def _render_month_grid(today_dt: date, busy_counts: dict[int, int]) -> str:
    """Multi-line text grid for the month containing today.

    Conky colour escapes are baked in:
    - today: ``${color5}`` (ok / green) so the eye lands on it instantly
    - 1-2 events on a day: ``${color3}`` (highlight / yellow)
    - 3+ events on a day: ``${color4}`` (alert / red)
    - empty days and past days: default foreground

    All inter-cell spacing uses U+00A0 (non-breaking space) because
    conky's text renderer collapses runs of ASCII spaces, which would
    otherwise crush "10 11" into "10 11" instead of "10 11" and break
    column alignment. Inside ``${color …}`` markup, ASCII spaces stay
    intact (conky parses the tag, then renders only the contained text).
    """
    nbsp = " "
    cal_obj = calendar_mod.Calendar(firstweekday=0)
    weeks = cal_obj.monthdayscalendar(today_dt.year, today_dt.month)
    header = nbsp.join(["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"])
    lines: list[str] = [f"${{color1}}{header}${{color}}"]
    for week in weeks:
        cells: list[str] = []
        for day in week:
            if day == 0:
                cells.append(nbsp * 2)
                continue
            # Two-char right-aligned cell; the padding space (when day
            # is single-digit) must also be NBSP.
            n = f"{day:>2d}".replace(" ", nbsp)
            count = busy_counts.get(day, 0)
            if day == today_dt.day:
                cells.append(f"${{color5}}{n}${{color}}")
            elif count >= 3:
                cells.append(f"${{color4}}{n}${{color}}")
            elif count >= 1:
                cells.append(f"${{color3}}{n}${{color}}")
            else:
                cells.append(n)
        lines.append(nbsp.join(cells))
    return "\n".join(lines)


# ── Daemon loop ───────────────────────────────────────────────────────────────


class Fetcher:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.token = load_token()
        self.client: httpx.AsyncClient | None = None
        self.wake_event = asyncio.Event()
        self.last_good_data: dict[str, Any] | None = None

    async def run(self) -> None:
        base_url = self.cfg["api_base_url"].rstrip("/")
        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        else:
            log.warning(
                "no token at %s; run `wayland-conky setup` first", TOKEN_PATH
            )

        timeout = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)
        async with httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
            http2=False,  # task backend is HTTP/1.1
        ) as client:
            self.client = client
            poll = max(5, int(self.cfg.get("poll_seconds", 30)))
            while True:
                await self._iteration()
                try:
                    await asyncio.wait_for(self.wake_event.wait(), timeout=poll)
                except TimeoutError:
                    pass
                self.wake_event.clear()

    async def _iteration(self) -> None:
        assert self.client is not None
        now_epoch = int(time.time())
        meta: dict[str, Any] = {
            "fetched_at_epoch": now_epoch,
            "fetched_at": datetime.now(UTC).isoformat(),
        }

        if not self.token:
            meta["last_error"] = "no token (run `wayland-conky setup`)"
            write_state({"data": self.last_good_data or {}, "meta": meta})
            return

        try:
            data = await fetch_all(self.client)
            self.last_good_data = data
            write_state({"data": data, "meta": meta})
            return
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                meta["last_error"] = "401: token rejected"
                notify(
                    "auth_401",
                    "wayland-conky: auth failed",
                    "Token rejected — run `wayland-conky setup`.",
                )
            else:
                meta["last_error"] = f"HTTP {e.response.status_code}"
                notify(
                    f"http_{e.response.status_code}",
                    "wayland-conky: server error",
                    f"{e.response.status_code} on {e.request.url.path}",
                )
        except (httpx.ConnectError, httpx.ConnectTimeout):
            meta["last_error"] = "network unreachable"
            notify(
                "net_down",
                "wayland-conky: offline",
                "Can't reach the task API — Tailscale up?",
            )
        except httpx.ReadTimeout:
            meta["last_error"] = "read timeout"
        except Exception as e:  # noqa: BLE001
            log.exception("unexpected fetch error")
            meta["last_error"] = f"{type(e).__name__}"

        write_state({"data": self.last_good_data or {}, "meta": meta})


def _install_sigusr1(fetcher: Fetcher, loop: asyncio.AbstractEventLoop) -> None:
    """SIGUSR1 = "wake up now" — used by widget-cli right after a
    mutation and by the Mod+Alt+R keybind. We just set an event the
    main loop is racing against the sleep on."""

    def handler() -> None:
        fetcher.wake_event.set()

    loop.add_signal_handler(signal.SIGUSR1, handler)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    fetcher = Fetcher()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_sigusr1(fetcher, loop)
    try:
        loop.run_until_complete(fetcher.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
