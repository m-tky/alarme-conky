# Override nixpkgs' conky-1.22.3 with upstream v1.24.0 so we get the
# Wayland-capable Lua + cairo bridge added in commit 8e4d4d0 (2026-04):
# the new ``conky_surface()`` Lua function returns a cairo_surface_t
# that works on both X11 and Wayland — the older
# ``cairo_xlib_surface_create(display, drawable, visual, w, h)`` path
# is X11-only and isn't reachable from a Wayland-out conky.
#
# Also flip ``luaCairoSupport`` on (nixpkgs default is false) so scripts
# can ``require('cairo')`` at runtime.
#
# Apply PR #2382 (open as of 2026-06): "fix: wayland double-buffer
# management and release listener". v1.24.0 ships display-wayland.cc
# with a single persistent shm buffer that conky clears + redraws in
# place on every cycle. The compositor can opportunistically re-scan
# that buffer between conky's clear and conky's commit (cursor enter
# / focus change / output recomposite), and it will read whatever
# torn / cleared state happens to be there — surfacing as occasional
# whole-panel flicker. The PR adds a second wl_buffer + a
# wl_buffer.release listener so conky draws into the buffer the
# compositor isn't currently reading from, and only attaches on
# commit. This is the structural fix that Lua-side offscreen
# compositing alone can only narrow but not eliminate.

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
  patches = (old.patches or []) ++ [
    ./patches/wayland-double-buffer.patch
  ];
  # libxi became a hard dependency between 1.22 and 1.24 — nixpkgs's
  # 1.22 derivation doesn't carry it, so we extend buildInputs here.
  buildInputs = (old.buildInputs or []) ++ [ libxi ];
})
