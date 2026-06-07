"""Config + token loading. One source of truth for all subcommands so
the fetcher and the CLI can never disagree on where they live."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
XDG_CACHE = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))

CONFIG_DIR = XDG_CONFIG / "wayland-conky"
CONFIG_PATH = CONFIG_DIR / "config.toml"
TOKEN_PATH = CONFIG_DIR / "token"
STATE_PATH = XDG_CACHE / "wayland-conky" / "state.json"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {"api_base_url": "http://localhost:8001"}
    with CONFIG_PATH.open("rb") as f:
        return tomllib.load(f)


def load_token() -> str:
    """Read the PAT. Raise ``RuntimeError`` if missing — every CLI command
    needs it, so we want a clear error rather than a 401 from the API."""
    if not TOKEN_PATH.exists():
        raise RuntimeError(
            f"No token at {TOKEN_PATH}. Run `wayland-conky setup` first."
        )
    tok = TOKEN_PATH.read_text().strip()
    if not tok:
        raise RuntimeError(f"Empty token file: {TOKEN_PATH}")
    return tok
