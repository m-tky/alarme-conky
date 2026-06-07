"""Poke the fetcher with SIGUSR1 so the panel refreshes within
milliseconds instead of after the next ``poll_seconds`` tick. Used
after every mutation the CLI performs."""

from __future__ import annotations

import subprocess


def wake_fetcher() -> None:
    try:
        subprocess.run(
            [
                "systemctl",
                "--user",
                "kill",
                "--signal=SIGUSR1",
                "wayland-conky-fetcher.service",
            ],
            check=False,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        # If systemctl is missing we're probably running in a dev shell
        # without the unit installed — silently no-op.
        pass
