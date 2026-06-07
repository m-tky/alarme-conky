"""Shared httpx client. Synchronous — every CLI command is one-shot,
so the async machinery only buys us complexity."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

import httpx

from .config import load_config, load_token


@contextlib.contextmanager
def client() -> Iterator[httpx.Client]:
    cfg = load_config()
    tok = load_token()
    with httpx.Client(
        base_url=cfg["api_base_url"].rstrip("/"),
        headers={"Authorization": f"Bearer {tok}"},
        timeout=httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0),
    ) as c:
        yield c
