"""Thin notify-send wrapper. Failures are silenced because CLI
commands shouldn't crash because libnotify isn't installed."""

from __future__ import annotations

import subprocess


def toast(summary: str, body: str = "", *, urgent: bool = False) -> None:
    cmd = ["notify-send", "-a", "wayland-conky"]
    if urgent:
        cmd += ["-u", "critical"]
    cmd += [summary]
    if body:
        cmd += [body]
    try:
        subprocess.run(cmd, check=False, timeout=3)
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
