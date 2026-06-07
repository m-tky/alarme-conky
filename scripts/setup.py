#!/usr/bin/env python3
"""``wayland-conky setup`` — install a Personal Access Token so the
fetcher and CLI can authenticate.

Self-issuance flow (the only flow shipped here):

1. Open the Alarme app → Settings → API keys → "Create key".
2. Copy the plaintext token (shown exactly once).
3. Run ``wayland-conky-setup`` — paste when prompted, or pass via
   ``--token`` / ``WAYLAND_CONKY_TOKEN`` env var. The token is written
   to ``~/.config/wayland-conky/token`` (chmod 600).

The earlier Firebase Admin SDK path required a service-account JSON,
which only the app maintainer has — that flow was developer-only and
is gone now. Every user (developers included) goes through the in-app
PAT issuance UI.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
CONFIG_DIR = XDG_CONFIG / "wayland-conky"
TOKEN_PATH = CONFIG_DIR / "token"

TOKEN_PREFIX = "tsk_pat_"


def _resolve_token(cli_value: str | None) -> str:
    if cli_value:
        return cli_value.strip()
    env = os.environ.get("WAYLAND_CONKY_TOKEN")
    if env:
        return env.strip()
    # Interactive prompt: getpass so the token doesn't echo into the
    # terminal scrollback. Falls back gracefully when stdin isn't a TTY.
    try:
        return getpass.getpass("Paste your PAT (input hidden): ").strip()
    except EOFError:
        raise SystemExit("No token provided.") from None


def _validate(token: str) -> None:
    if not token:
        raise SystemExit("Empty token.")
    if not token.startswith(TOKEN_PREFIX):
        raise SystemExit(
            f"Token doesn't start with {TOKEN_PREFIX!r}. Are you sure you "
            f"pasted a wayland-conky / Alarme PAT (not a Firebase ID token)?"
        )


def write_token(token: str) -> None:
    """Persist only the freshly-pasted PAT. config.toml is managed by
    home-manager (apiBaseUrl etc.); we never touch it here."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o700)
    TOKEN_PATH.write_text(token + "\n")
    os.chmod(TOKEN_PATH, 0o600)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--token", default=None,
        help="PAT plaintext. If omitted, prompted on stdin (hidden); "
             "falls back to WAYLAND_CONKY_TOKEN env var.",
    )
    args = p.parse_args()

    token = _resolve_token(args.token)
    _validate(token)
    write_token(token)

    print(f"→ wrote {TOKEN_PATH}")
    print("Restart the fetcher to pick up the new credentials:")
    print("    systemctl --user restart wayland-conky-fetcher.service")
    return 0


if __name__ == "__main__":
    sys.exit(main())
