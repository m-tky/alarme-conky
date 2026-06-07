"""Show / hide the conky panel by toggling its systemd user service.

There's no in-process API for this on Wayland conky, so this is the
cleanest path: the unit owns lifecycle, we just flip it."""

from __future__ import annotations

import argparse
import subprocess

from .shared.notify import toast

UNIT = "wayland-conky.service"


def _is_active() -> bool:
    p = subprocess.run(
        ["systemctl", "--user", "is-active", UNIT],
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )
    return p.stdout.strip() == "active"


def main(_args: argparse.Namespace) -> int:
    try:
        action = "stop" if _is_active() else "start"
        subprocess.run(
            ["systemctl", "--user", action, UNIT], check=False, timeout=5
        )
        toast("Conky", f"{action}ped")
    except (FileNotFoundError, subprocess.SubprocessError) as e:
        toast("Conky toggle failed", str(e), urgent=True)
        return 1
    return 0


def add_args(_p: argparse.ArgumentParser) -> None:
    pass
