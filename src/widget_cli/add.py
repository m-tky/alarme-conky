"""``task-widget add`` — opens the unified GTK4 task form.

The form's contract: Title is focused on open, Enter from Title
submits with everything else at defaults. So "quick capture speed"
and "rich edit when needed" share the same UI.
"""

from __future__ import annotations

import argparse

from . import task_form


def main(_args: argparse.Namespace) -> int:
    return task_form.show()


def add_args(_p: argparse.ArgumentParser) -> None:
    pass
