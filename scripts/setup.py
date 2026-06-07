#!/usr/bin/env python3
"""``wayland-conky setup`` — issue a Personal Access Token and drop it
on disk so the fetcher + CLI can authenticate.

The task project's Firebase configuration disables email/password
sign-in (Google OAuth only), so we cannot use signInWithPassword from
a script. Instead we use the **service account JSON** to mint a custom
token for the target user and exchange it for an ID token via the
Firebase REST endpoint. That ID token is then used to call
``/auth/api-keys``.

Inputs the user provides:
- Email of the target user (we look up the Firebase UID by email
  through the admin SDK).
- Path to the service-account JSON (auto-detected at the default
  location under ``~/Code/task``).

The script is idempotent: existing PATs named ``wayland-conky`` are
deleted before a fresh one is issued, so repeated runs leave at most
one active key.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

import firebase_admin
from firebase_admin import auth, credentials

XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
CONFIG_DIR = XDG_CONFIG / "wayland-conky"
CONFIG_PATH = CONFIG_DIR / "config.toml"
TOKEN_PATH = CONFIG_DIR / "token"

# Generic defaults — overridable via CLI flag, env var, or config.toml
# managed by home-manager. None of these defaults identify a specific
# deployment, so the repo is safe to publish as-is.
DEFAULT_API_BASE = "http://localhost:8001"
DEFAULT_KEY_NAME = "wayland-conky"
# Service account JSON path: put yours at ~/.config/wayland-conky/service-account.json
# or override with --service-account / SERVICE_ACCOUNT_PATH env var.
DEFAULT_SERVICE_ACCOUNT = CONFIG_DIR / "service-account.json"


def _read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _resolve_firebase_api_key(cli_value: str | None) -> str:
    """Firebase Web API key resolution order: CLI flag, env, config.toml.
    We require an explicit value because the key identifies the Firebase
    project the PAT will be issued against — there's no sensible
    fallback we could ship in a public repo."""
    if cli_value:
        return cli_value
    env = os.environ.get("FIREBASE_WEB_API_KEY")
    if env:
        return env
    cfg = _read_toml(CONFIG_PATH)
    key = cfg.get("firebase_web_api_key")
    if key:
        return key
    raise SystemExit(
        "Missing Firebase Web API key. Provide it via:\n"
        "  - --firebase-api-key <key>, or\n"
        "  - FIREBASE_WEB_API_KEY env var, or\n"
        f"  - firebase_web_api_key = \"…\" in {CONFIG_PATH}\n"
        "  (home-manager option: programs.wayland-conky.firebaseWebApiKey)\n"
        "The Web API key is in your Firebase project's web app config —\n"
        "see https://firebase.google.com/docs/web/learn-more#config-object"
    )


def _resolve_api_base(cli_value: str | None) -> str:
    if cli_value:
        return cli_value
    env = os.environ.get("API_BASE_URL")
    if env:
        return env
    cfg = _read_toml(CONFIG_PATH)
    return cfg.get("api_base_url") or DEFAULT_API_BASE


def _post_json(url: str, body: dict, headers: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8") or "{}")
        except Exception:  # noqa: BLE001
            payload = {}
        return e.code, payload


def _get_json(url: str, headers: dict) -> tuple[int, list | dict]:
    req = urllib.request.Request(url, method="GET")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        return e.code, {}


def _delete(url: str, headers: dict) -> int:
    req = urllib.request.Request(url, method="DELETE")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def signin_with_admin(
    service_account: Path, email: str, firebase_api_key: str
) -> str:
    """Use the service account to mint a custom token for the user and
    exchange it for a Firebase ID token via the REST endpoint.

    Returns the ID token (valid for ~1h, which is plenty for the
    handful of HTTP calls this script makes)."""
    if not service_account.exists():
        raise SystemExit(
            f"Service account JSON not found: {service_account}\n"
            f"Place it there (or symlink it) and re-run, or pass\n"
            f"  --service-account /path/to/serviceAccount.json"
        )

    cred = credentials.Certificate(str(service_account))
    # Guard against being called twice in the same process (rare from a
    # CLI but cheap insurance).
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)

    try:
        user = auth.get_user_by_email(email)
    except auth.UserNotFoundError as e:
        raise SystemExit(
            f"No Firebase user with email {email}. Sign in via the Flutter "
            f"app at least once to provision the account."
        ) from e

    custom_token = auth.create_custom_token(user.uid)
    # firebase-admin returns bytes; the REST endpoint wants a string.
    if isinstance(custom_token, bytes):
        custom_token = custom_token.decode("ascii")

    url = (
        "https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken"
        f"?key={firebase_api_key}"
    )
    status, body = _post_json(
        url, {"token": custom_token, "returnSecureToken": True}
    )
    if status != 200 or "idToken" not in body:
        msg = body.get("error", {}).get("message", f"HTTP {status}")
        raise SystemExit(f"Custom-token exchange failed: {msg}")
    return body["idToken"]


def rotate(api_base: str, id_token: str, key_name: str) -> str:
    """Delete every existing PAT with the given name, mint a new one,
    return the plaintext token."""
    headers = {"Authorization": f"Bearer {id_token}"}
    status, listed = _get_json(f"{api_base}/api/v1/auth/api-keys", headers)
    if status != 200:
        raise SystemExit(
            f"Listing existing keys failed ({status}). Has the user "
            f"completed first-login via the Flutter app yet?"
        )
    if isinstance(listed, list):
        for row in listed:
            if isinstance(row, dict) and row.get("name") == key_name:
                _delete(f"{api_base}/api/v1/auth/api-keys/{row['id']}", headers)

    status, body = _post_json(
        f"{api_base}/api/v1/auth/api-keys",
        {"name": key_name},
        headers=headers,
    )
    if status != 201 or "token" not in body:
        raise SystemExit(f"Issuance failed ({status}): {body}")
    return body["token"]


def write_token(token: str) -> None:
    """Persist only the freshly-minted PAT. config.toml is owned by
    home-manager (or whatever wrote it first); we never overwrite it
    here because doing so would clobber the Firebase API key and any
    other settings the user configured."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o700)
    TOKEN_PATH.write_text(token + "\n")
    os.chmod(TOKEN_PATH, 0o600)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--api-base", default=None,
        help=f"Task API base URL. Falls back to env API_BASE_URL, then "
             f"config.toml::api_base_url, then {DEFAULT_API_BASE}.",
    )
    p.add_argument(
        "--name", default=DEFAULT_KEY_NAME,
        help=f"PAT name (default: {DEFAULT_KEY_NAME})",
    )
    p.add_argument(
        "--email", default=None,
        help="Firebase email to issue PAT for. Prompted if omitted.",
    )
    p.add_argument(
        "--service-account", default=str(DEFAULT_SERVICE_ACCOUNT),
        help=f"Path to Firebase Admin service account JSON "
             f"(default: {DEFAULT_SERVICE_ACCOUNT}).",
    )
    p.add_argument(
        "--firebase-api-key", default=None,
        help="Firebase Web API key. Falls back to env FIREBASE_WEB_API_KEY, "
             "then config.toml::firebase_web_api_key.",
    )
    args = p.parse_args()

    api_base = _resolve_api_base(args.api_base)
    firebase_api_key = _resolve_firebase_api_key(args.firebase_api_key)

    print(f"→ task API: {api_base}")
    email = args.email or input("Email: ").strip()

    print(f"→ signing in via Firebase Admin SDK ({args.service_account})…")
    id_token = signin_with_admin(
        Path(args.service_account), email, firebase_api_key
    )

    print(f"→ rotating PAT named '{args.name}'…")
    token = rotate(api_base, id_token, args.name)

    print(f"→ writing {TOKEN_PATH}")
    write_token(token)

    print("Done. Restart the fetcher to pick up the new credentials:")
    print("    systemctl --user restart wayland-conky-fetcher.service")
    return 0


if __name__ == "__main__":
    sys.exit(main())
