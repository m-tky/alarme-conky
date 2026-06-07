"""Pomodoro overlay — a layer-shell ring widget that sits above
normal windows whenever a session is active.

Why a separate process from conky: the conky panel lives on the
``bottom`` wlr-layer-shell layer (intentional — the user doesn't
want their full panel to climb on top of working windows). But
Pomodoro is the one piece they want visible mid-task, so it goes
into its own ``top`` layer surface that auto-hides between sessions.

Lifecycle: a systemd user service launches this once at session
start. Polls ``state.json`` once per second; on transitions in/out
of "active session" it presents/hides the window. While active the
DrawingArea repaints on every tick so the remaining MM:SS counts
down without re-fetching from the backend.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, GLib, Gtk, Gtk4LayerShell  # noqa: E402


STATE_PATH = (
    Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    / "wayland-conky"
    / "state.json"
)

# Tuning. Sized for ~80px visible diameter; bump RADIUS for a bigger
# ring (and re-center text by adjusting FONT_SIZE).
SIZE = 96
RADIUS = 36
THICKNESS = 6
FONT_SIZE = 16
MARGIN_TOP = 24
MARGIN_RIGHT = 24


def _hex_rgb(h: str) -> tuple[float, float, float]:
    """Convert a 6-char hex string to an (r, g, b) triple in [0, 1]."""
    return (
        int(h[0:2], 16) / 255.0,
        int(h[2:4], 16) / 255.0,
        int(h[4:6], 16) / 255.0,
    )


# Palette — kept in sync with Nightfox accent / muted / fg. If we later
# want this to track the user's selected theme we can pass colours
# through env vars from the systemd unit, same trick as the conky
# block scripts.
COLOUR_ACCENT = _hex_rgb("9d79d6")
COLOUR_MUTED = _hex_rgb("71839b")
COLOUR_FG = _hex_rgb("cdcecf")


def _read_pomodoro() -> dict[str, Any] | None:
    """Return the ``.data.pomodoro`` object if present, else None.
    Returns None on any error (missing file, partial write, malformed
    JSON) so the overlay simply hides instead of crashing the loop."""
    try:
        with STATE_PATH.open() as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return ((data.get("data") or {}).get("pomodoro")) or None


class PomoOverlay(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="org.wayland-conky.PomoOverlay")
        self._window: Gtk.ApplicationWindow | None = None
        self._area: Gtk.DrawingArea | None = None
        self._pomo: dict[str, Any] | None = None
        # Hold a flag for the current visibility — we only call
        # ``show`` / ``hide`` on transitions, since redundant calls
        # can trigger an unnecessary surface ack-configure round-trip.
        self._visible = False

    def do_activate(self) -> None:
        if self._window is not None:
            self._window.present()
            return

        # Apply the shared Nightfox theme so palette tokens are
        # available for any future GTK widgets (the ring itself is
        # cairo-drawn; the theme matters for text bubbles, popovers,
        # etc. should we add them).
        from .shared.theme import apply_theme
        apply_theme()

        win = Gtk.ApplicationWindow(application=self)
        win.set_default_size(SIZE, SIZE)
        win.set_decorated(False)
        win.set_resizable(False)

        # Layer-shell setup. ``top`` (not ``overlay``) so the ring
        # sits above normal tiled windows but yields to fullscreen
        # apps — when a video / IDE is full-screen, the user is
        # focused on it and the ring would be intrusive.
        Gtk4LayerShell.init_for_window(win)
        Gtk4LayerShell.set_layer(win, Gtk4LayerShell.Layer.TOP)
        Gtk4LayerShell.set_anchor(win, Gtk4LayerShell.Edge.TOP, True)
        Gtk4LayerShell.set_anchor(win, Gtk4LayerShell.Edge.RIGHT, True)
        Gtk4LayerShell.set_margin(win, Gtk4LayerShell.Edge.TOP, MARGIN_TOP)
        Gtk4LayerShell.set_margin(win, Gtk4LayerShell.Edge.RIGHT, MARGIN_RIGHT)
        # Pure visual surface — never steal input focus.
        Gtk4LayerShell.set_keyboard_mode(
            win, Gtk4LayerShell.KeyboardMode.NONE
        )
        # Don't reserve space — we float over the workspace rather
        # than push tiled windows aside.
        Gtk4LayerShell.set_exclusive_zone(win, 0)
        Gtk4LayerShell.set_namespace(win, "pomo-overlay")

        # Transparent window background. We paint the ring + text
        # ourselves; the surrounding pixels stay see-through.
        win.add_css_class("pomo-overlay")
        provider = Gtk.CssProvider()
        provider.load_from_string(
            ".pomo-overlay, .pomo-overlay > * { background: transparent; }"
        )
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
            )

        area = Gtk.DrawingArea()
        area.set_content_width(SIZE)
        area.set_content_height(SIZE)
        area.set_draw_func(self._on_draw)
        win.set_child(area)

        self._window = win
        self._area = area

        # Tick once now so the initial visibility lines up with state;
        # then every second thereafter while the application is alive.
        GLib.timeout_add(1000, self._tick)
        self._tick()

    # ── lifecycle ──────────────────────────────────────────────────────

    def _tick(self) -> bool:
        pomo = _read_pomodoro()
        self._pomo = pomo
        if self._window is None or self._area is None:
            return True
        if pomo is None:
            if self._visible:
                self._window.hide()
                self._visible = False
        else:
            if not self._visible:
                self._window.present()
                self._visible = True
            self._area.queue_draw()
        return True  # keep ticking

    # ── rendering ──────────────────────────────────────────────────────

    def _on_draw(
        self, _area: Gtk.DrawingArea, cr, w: int, h: int
    ) -> None:
        pomo = self._pomo
        if pomo is None:
            return
        try:
            ratio = float(pomo.get("elapsed_ratio") or 0.0)
        except (TypeError, ValueError):
            ratio = 0.0
        ratio = max(0.0, min(1.0, ratio))
        remaining = str(pomo.get("remaining") or "")

        cx, cy = w / 2.0, h / 2.0

        # Faint track ring.
        cr.set_source_rgba(*COLOUR_MUTED, 0.30)
        cr.set_line_width(THICKNESS)
        cr.arc(cx, cy, RADIUS, 0, 2 * math.pi)
        cr.stroke()

        # Progress arc — accent, rounded cap so the leading edge
        # reads as a "comet" instead of a chopped line.
        cr.set_source_rgba(*COLOUR_ACCENT, 1.0)
        cr.set_line_width(THICKNESS)
        cr.set_line_cap(1)  # CAIRO_LINE_CAP_ROUND
        start = -math.pi / 2
        cr.arc(cx, cy, RADIUS, start, start + 2 * math.pi * ratio)
        cr.stroke()

        # Remaining time centred inside the ring.
        cr.set_source_rgba(*COLOUR_FG, 1.0)
        cr.select_font_face("Moralerspace Argon", 0, 1)  # NORMAL, BOLD
        cr.set_font_size(FONT_SIZE)
        x_bearing, y_bearing, tw, th, *_ = cr.text_extents(remaining)
        cr.move_to(cx - tw / 2 - x_bearing, cy - y_bearing / 2.0 - th / 2.0)
        cr.show_text(remaining)


def main(_args: argparse.Namespace) -> int:
    app = PomoOverlay()
    # Hold the app so the timeout keeps firing even with no visible
    # window — the overlay needs to stay alive across off→on
    # transitions of pomodoro state.
    app.hold()
    return app.run(None) or 0


def add_args(_p: argparse.ArgumentParser) -> None:
    pass
