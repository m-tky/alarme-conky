"""Quick + guided task add.

Quick mode (default): one fuzzel line. The line is split into:
- ``#proj`` — project lookup (substring against the user's project names)
- ``@HH[:MM]`` — fixed_start_time
- ``!high`` / ``!med`` / ``!low`` — priority
- ``~tag`` — tag name (may repeat)
- ``*`` — is_important
- ``!!`` — is_urgent
Anything left after removing those tokens is the title. If the title
itself looks like it carries a date phrase (e.g. ``明日`` or ``来週``)
we send it through the backend's ``/parse-deadline`` endpoint to
extract a ``deadline``; on parse failure we just post with no deadline
rather than block the user.

Guided mode (``--guided``): three sequential fuzzel prompts — title,
project picker, deadline picker. Slower but exact.
"""

from __future__ import annotations

import argparse
import re
from typing import Any

from .shared.fetcher_signal import wake_fetcher
from .shared.format import parse_validation_error
from .shared.fuzzel import CancelledByUser, pick, prompt
from .shared.http import client
from .shared.notify import toast

# Inline-syntax token patterns. We strip these out of the title before
# building the request body.
_PROJ_RE = re.compile(r"(?<!\S)#([^\s#@!~*]+)")
_TIME_RE = re.compile(r"(?<!\S)@(\d{1,2})(?::?(\d{2}))?")
_PRI_RE = re.compile(r"(?<!\S)!(high|med|low)\b", re.IGNORECASE)
_TAG_RE = re.compile(r"(?<!\S)~([^\s#@!~*]+)")
_URGENT_RE = re.compile(r"(?<!\S)!!")
_IMPORTANT_RE = re.compile(r"(?<!\S)\*(?=\s|$)")


def _parse_inline(line: str) -> dict[str, Any]:
    """Pull tokens out of a freeform line. Returns a dict that maps
    cleanly onto the backend's TaskCreate fields."""
    extracted: dict[str, Any] = {"title": line}

    project = _PROJ_RE.search(line)
    if project:
        extracted["_project_query"] = project.group(1)

    time_m = _TIME_RE.search(line)
    if time_m:
        h = int(time_m.group(1))
        m = int(time_m.group(2)) if time_m.group(2) else 0
        if 0 <= h < 24 and 0 <= m < 60:
            extracted["fixed_start_time"] = f"{h:02d}:{m:02d}:00"

    pri = _PRI_RE.search(line)
    if pri:
        extracted["priority"] = {"high": 3, "med": 2, "low": 1}[pri.group(1).lower()]

    tags = _TAG_RE.findall(line)
    if tags:
        extracted["_tag_names"] = tags

    if _URGENT_RE.search(line):
        extracted["is_urgent"] = True
    if _IMPORTANT_RE.search(line):
        extracted["is_important"] = True

    # Strip every matched token from the visible title. Order: longest
    # patterns first so ``!!`` isn't half-eaten by the ``!`` priority.
    cleaned = line
    for pat in (_URGENT_RE, _PRI_RE, _PROJ_RE, _TIME_RE, _TAG_RE, _IMPORTANT_RE):
        cleaned = pat.sub("", cleaned)
    extracted["title"] = " ".join(cleaned.split()).strip()
    return extracted


def _resolve_project(c, query: str) -> str | None:
    """Substring-match the user's projects. /projects returns a bare
    JSON list (list[ProjectOut]); no envelope, so we treat the body
    that way and fall back to dict-with-`data` for forward-compat."""
    r = c.get("/api/v1/projects")
    if r.status_code != 200:
        return None
    body = r.json()
    items = body if isinstance(body, list) else (body.get("data") or [])
    q = query.lower()
    for p in items:
        if isinstance(p, dict) and q in (p.get("name") or "").lower():
            return p.get("id")
    return None


def _resolve_tag_ids(c, names: list[str]) -> list[str]:
    """Map ``~tagname`` tokens to UUIDs. Names that don't match an
    existing tag get auto-created (POST /tags) so the user can introduce
    new tags inline — TickTick-style. Color picks the backend default
    "grey" since we have no context for choosing better."""
    if not names:
        return []
    r = c.get("/api/v1/tags")
    body = r.json() if r.status_code == 200 else []
    existing = body if isinstance(body, list) else (body.get("data") or [])
    by_name = {
        (t.get("name") or "").lower(): t.get("id")
        for t in existing
        if isinstance(t, dict)
    }
    out: list[str] = []
    for name in names:
        tid = by_name.get(name.lower())
        if tid is None:
            cr = c.post("/api/v1/tags", json={"name": name})
            if cr.status_code in (200, 201):
                tid = cr.json().get("id")
        if tid:
            out.append(tid)
    return out


def _try_parse_deadline(c, text: str) -> dict | None:
    """Ask the backend to extract a date phrase from the title. Returns
    a dict ``{date_only, parsed (ISO datetime), time_included}`` or
    None on parse failure / API error.

    The endpoint returns 422 when no date phrase was detected; we treat
    that as a non-error so a plain title without a date phrase just
    creates an unscheduled task instead of toasting an error."""
    try:
        r = c.post("/api/v1/parse-deadline", json={"text": text})
        if r.status_code == 200:
            return r.json()
    except Exception:  # noqa: BLE001
        pass
    return None


def _quick_add(line: str) -> None:
    parsed = _parse_inline(line)
    if not parsed["title"]:
        toast("Add cancelled", "Title was empty after stripping tokens.")
        return

    # ``status`` is intentionally absent — TaskCreate.extra = forbid, and
    # new tasks default to not_yet server-side.
    payload: dict[str, Any] = {"title": parsed["title"]}
    for k in ("fixed_start_time", "priority", "is_urgent", "is_important"):
        if k in parsed:
            payload[k] = parsed[k]

    with client() as c:
        if "_project_query" in parsed:
            pid = _resolve_project(c, parsed["_project_query"])
            if pid:
                payload["project_id"] = pid
        if "_tag_names" in parsed:
            tag_ids = _resolve_tag_ids(c, parsed["_tag_names"])
            if tag_ids:
                payload["tag_ids"] = tag_ids
        # Route the parsed date: time_included → real deadline
        # (datetime, the design-doc Calendar surface), otherwise treat
        # it as "do it on that day" → scheduled_date (TaskChute Today).
        # When the user already pinned @HH:MM inline we honour that as
        # fixed_start_time on the chosen scheduled_date.
        parsed_date = _try_parse_deadline(c, parsed["title"])
        if parsed_date:
            if parsed_date.get("time_included"):
                payload["deadline"] = parsed_date["parsed"]
            else:
                payload["scheduled_date"] = parsed_date["date_only"]

        r = c.post("/api/v1/tasks", json=payload)
        if r.status_code not in (200, 201):
            toast(
                "Add failed",
                parse_validation_error(r.status_code, r.text),
                urgent=True,
            )
            return
        created = r.json() if r.headers.get("content-type", "").startswith(
            "application/json"
        ) else {}

    wake_fetcher()
    toast("Task added", _summary(created, parsed))


def _summary(created: dict, parsed: dict) -> str:
    """One-line confirmation of where the task landed: title + (scheduled/
    deadline/Inbox) + (Pomodoro-style hint when fixed_start_time set)."""
    title = created.get("title") or parsed["title"]
    where = []
    if (t := (created.get("fixed_start_time") or "")[:5]):
        where.append(t)
    if created.get("deadline"):
        where.append(f"⚠ {created['deadline'][:10]}")
    elif (s := created.get("scheduled_date")):
        where.append(s)
    else:
        where.append("Inbox")
    if created.get("is_important"):
        where.append("★")
    if created.get("is_urgent"):
        where.append("!")
    return f"{title}  ·  {' '.join(where)}"


def _guided_add() -> None:
    try:
        title = prompt("Title")
    except CancelledByUser:
        return

    with client() as c:
        projects_body = c.get("/api/v1/projects").json()
        pitems = projects_body if isinstance(projects_body, list) else (
            projects_body.get("data") or []
        )
        proj_choices: list[tuple[str, str | None]] = [("📥 Inbox (no project)", None)]
        proj_choices += [
            (f"#{p['name']}", p["id"]) for p in pitems if isinstance(p, dict)
        ]
        try:
            project_id = pick("Project", proj_choices)
        except CancelledByUser:
            project_id = None

        date_choices = [
            ("Today (scheduled)", "today"),
            ("Tomorrow (scheduled)", "tomorrow"),
            ("This Saturday", "saturday"),
            ("Next Monday", "monday_next"),
            ("Unscheduled", None),
            ("type a date or phrase…", "custom"),
        ]
        try:
            chosen = pick("When", date_choices)
        except CancelledByUser:
            chosen = None
        parsed_date: dict | None = None
        if chosen == "custom":
            try:
                free = prompt("Date or phrase (e.g. 'next friday', '明日 14:00')")
                parsed_date = _try_parse_deadline(c, free)
                if not parsed_date:
                    toast("Add", f"Couldn't parse: {free}", urgent=True)
                    return
            except CancelledByUser:
                pass
        elif chosen is not None:
            parsed_date = _try_parse_deadline(c, chosen.replace("_", " "))

        priority_choices = [
            ("(none)", 0),
            ("Low", 1),
            ("Medium", 2),
            ("High", 3),
        ]
        try:
            priority = pick("Priority", priority_choices)
        except CancelledByUser:
            priority = 0

        flag_choices = [
            ("(no flags)", set()),
            ("★ Important", {"is_important"}),
            ("! Urgent", {"is_urgent"}),
            ("★ Important + ! Urgent", {"is_important", "is_urgent"}),
        ]
        try:
            flags = pick("Flags", flag_choices)
        except CancelledByUser:
            flags = set()

        payload: dict[str, Any] = {"title": title}
        if project_id:
            payload["project_id"] = project_id
        if parsed_date:
            if parsed_date.get("time_included"):
                payload["deadline"] = parsed_date["parsed"]
            else:
                payload["scheduled_date"] = parsed_date["date_only"]
        if priority > 0:
            payload["priority"] = priority
        if "is_important" in flags:
            payload["is_important"] = True
        if "is_urgent" in flags:
            payload["is_urgent"] = True

        r = c.post("/api/v1/tasks", json=payload)
        if r.status_code not in (200, 201):
            toast(
                "Add failed",
                parse_validation_error(r.status_code, r.text),
                urgent=True,
            )
            return
        created = r.json() if r.headers.get("content-type", "").startswith(
            "application/json"
        ) else {}

    wake_fetcher()
    toast("Task added", _summary(created, {"title": title}))


def add_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--guided", action="store_true", help="multi-step prompt")


def main(args: argparse.Namespace) -> int:
    if args.guided:
        _guided_add()
        return 0
    try:
        line = prompt("Add")
    except CancelledByUser:
        return 0
    _quick_add(line)
    return 0
