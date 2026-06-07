"""Shared GTK/libadwaita theme for the wayland-conky widget windows.

Every GTK surface in this project (TaskForm, CalendarPopup,
PomoOverlay) calls ``apply_theme()`` at startup. That installs a
display-wide CSS provider that:

- pins the font to Moralerspace Argon (matches the conky panel and
  fuzzel, so the windows feel like part of one product)
- overrides libadwaita's accent + named colour tokens to the
  Nightfox palette used by the conky panel — buttons, focus rings,
  selected rows, badges, sliders all pick up the section blue
- forces the system colour scheme to dark, so the Nightfox tokens
  read against the right backgrounds even when GNOME is set to
  Light system-wide
- adds a small set of bespoke classes (.kpi-card, .muted-label,
  .panel-divider) so individual screens can opt into the modern
  card aesthetic without re-defining the visual language

Keeping all of this in one place means a palette swap is a one-line
edit instead of a sweep across every window.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402


# Nightfox palette tokens. Mirror modules/home.nix → palettes.nightfox.
_PALETTE = {
    "bg":        "#1e2030",
    "fg":        "#cdcecf",
    "muted":     "#71839b",
    "divider":   "#39506d",
    "section":   "#719cd6",
    "section_l": "#86abdc",
    "counter":   "#63cdcf",
    "highlight": "#dbc074",
    "alert":     "#c94f6d",
    "alert_l":   "#d16983",
    "ok":        "#81b29a",
    "ok_l":      "#8ebaa4",
    "accent":    "#9d79d6",
    "card_bg":   "#262a3d",
    "header_bg": "#1a1c2c",
}

_THEME_CSS = f"""
/* Pin the font system-wide. Moralerspace Argon is the panel font
   and ships a Bold cut; libadwaita's Cantarell default felt
   visually detached. */
* {{ font-family: "Moralerspace Argon", monospace; }}

/* libadwaita named colour tokens — re-mapped to Nightfox. Touching
   the *_bg_color tokens flips every libadwaita-shipped widget at
   once (buttons, switches, sliders, focus rings, AdwBanner accents,
   AdwToast). */
@define-color window_bg_color       {_PALETTE['bg']};
@define-color window_fg_color       {_PALETTE['fg']};
@define-color view_bg_color         {_PALETTE['card_bg']};
@define-color view_fg_color         {_PALETTE['fg']};
@define-color card_bg_color         {_PALETTE['card_bg']};
@define-color card_fg_color         {_PALETTE['fg']};
@define-color sidebar_bg_color      {_PALETTE['bg']};
@define-color sidebar_fg_color      {_PALETTE['fg']};
@define-color headerbar_bg_color    {_PALETTE['header_bg']};
@define-color headerbar_fg_color    {_PALETTE['fg']};
@define-color headerbar_border_color alpha({_PALETTE['divider']}, 0.6);
@define-color popover_bg_color      {_PALETTE['card_bg']};
@define-color popover_fg_color      {_PALETTE['fg']};

@define-color accent_bg_color       {_PALETTE['section']};
@define-color accent_color          {_PALETTE['section_l']};
@define-color accent_fg_color       {_PALETTE['bg']};

@define-color destructive_bg_color  {_PALETTE['alert']};
@define-color destructive_color     {_PALETTE['alert_l']};
@define-color destructive_fg_color  {_PALETTE['bg']};

@define-color success_bg_color      {_PALETTE['ok']};
@define-color success_color         {_PALETTE['ok_l']};
@define-color success_fg_color      {_PALETTE['bg']};

@define-color warning_bg_color      {_PALETTE['highlight']};
@define-color warning_color         {_PALETTE['highlight']};
@define-color warning_fg_color      {_PALETTE['bg']};

/* Bespoke utility classes. Used by individual screens to opt into
   the conky-panel card aesthetic. */

.panel-card {{
  background: alpha({_PALETTE['section']}, 0.08);
  border-radius: 12px;
  padding: 16px;
}}

.panel-divider {{
  background: linear-gradient(to right,
    transparent 0%,
    alpha({_PALETTE['divider']}, 0.6) 50%,
    transparent 100%);
  min-height: 1px;
}}

.muted-label {{
  color: alpha({_PALETTE['muted']}, 0.85);
}}

.section-label {{
  color: {_PALETTE['section_l']};
  font-weight: 700;
  letter-spacing: 0.4px;
}}

.kpi-number {{
  font-size: 28px;
  font-weight: 400;
}}

/* Slightly nicer entry rows: tighter borders, smoother focus. */
entryrow, spinrow, comborow {{
  background: alpha({_PALETTE['card_bg']}, 0.7);
  border-radius: 10px;
}}

button.suggested-action {{
  font-weight: 600;
}}

/* Calendar cells in calendar-popup: pill-shaped with subtle hover. */
.cal-cell {{
  border-radius: 999px;
  padding: 6px 4px;
  min-width: 32px;
  transition: background 120ms;
}}
.cal-cell:hover {{
  background: alpha({_PALETTE['section']}, 0.16);
}}
.cal-cell.today {{
  background: {_PALETTE['accent']};
  color: {_PALETTE['bg']};
  font-weight: 700;
}}
.cal-cell.busy {{
  color: {_PALETTE['highlight']};
  font-weight: 600;
}}
.cal-cell.busy-high {{
  color: {_PALETTE['alert']};
  font-weight: 600;
}}
.cal-cell.adjacent {{
  color: alpha({_PALETTE['muted']}, 0.5);
}}
.cal-cell.past {{
  color: alpha({_PALETTE['muted']}, 0.7);
}}
"""


_APPLIED = False


def apply_theme() -> None:
    """Idempotent — safe to call from every entry point's main()."""
    global _APPLIED
    if _APPLIED:
        return
    display = Gdk.Display.get_default()
    if display is None:
        return
    provider = Gtk.CssProvider()
    provider.load_from_string(_THEME_CSS)
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    # Force dark scheme so the Nightfox tokens read against the
    # backgrounds they were chosen for. The user can still switch
    # the *system* scheme separately; we only force ours.
    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
    _APPLIED = True


# Palette accessor for code that needs raw hex values (e.g. cairo
# drawing inside the pomodoro overlay ring).
def palette() -> dict[str, str]:
    return dict(_PALETTE)
