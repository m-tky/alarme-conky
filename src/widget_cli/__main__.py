"""Subcommand router. Each subcommand module exposes ``main(args)`` and
``add_args(parser)`` so this file stays a thin wiring layer."""

from __future__ import annotations

import argparse
import sys

from . import (
    add,
    calendar_popup,
    delete,
    done,
    habit,
    jump,
    palette,
    pomodoro,
    snooze,
    toggle_conky,
)

SUBCOMMANDS = {
    "add": add,
    "done": done,
    "delete": delete,
    "snooze": snooze,
    "jump": jump,
    "pomodoro": pomodoro,
    "habit": habit,
    "palette": palette,
    "toggle-conky": toggle_conky,
    "calendar": calendar_popup,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="task-widget")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, mod in SUBCOMMANDS.items():
        sp = sub.add_parser(name)
        mod.add_args(sp)
        sp.set_defaults(_mod=mod)
    args = parser.parse_args(argv)
    try:
        return args._mod.main(args)
    except RuntimeError as e:
        # Token missing / config error — surface clearly instead of
        # dumping a traceback at the user.
        from .shared.notify import toast

        toast("wayland-conky", str(e), urgent=True)
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
