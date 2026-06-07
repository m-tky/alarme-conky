# Override nixpkgs' conky-1.22.3 with upstream v1.24.0 so we get the
# Wayland-capable Lua + cairo bridge added in commit 8e4d4d0 (2026-04):
# the new ``conky_surface()`` Lua function returns a cairo_surface_t
# that works on both X11 and Wayland — the older
# ``cairo_xlib_surface_create(display, drawable, visual, w, h)`` path
# is X11-only and isn't reachable from a Wayland-out conky.
#
# Also flip ``luaCairoSupport`` on (nixpkgs default is false) so scripts
# can ``require('cairo')`` at runtime.

{ conky, fetchFromGitHub, libxi }:

let
  version = "1.24.0";
in
(conky.override {
  luaSupport = true;
  luaCairoSupport = true;
  luaImlib2Support = false;
  waylandSupport = true;
  x11Support = true;
}).overrideAttrs (old: {
  inherit version;
  src = fetchFromGitHub {
    owner = "brndnmtthws";
    repo = "conky";
    tag = "v${version}";
    hash = "sha256-jd10v4tldZrtQSV9vG5szvH62OsZZ9MWoM8hU5rFujo=";
  };
  # libxi became a hard dependency between 1.22 and 1.24 — nixpkgs's
  # 1.22 derivation doesn't carry it, so we extend buildInputs here.
  buildInputs = (old.buildInputs or []) ++ [ libxi ];
})
