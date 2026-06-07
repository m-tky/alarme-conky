{ stdenvNoCC, pyEnv, makeWrapper, wrapGAppsHook4, gtk4, libadwaita
, gtk4-layer-shell, gobject-introspection, fuzzel, libnotify, jq
, xdg-utils, wl-clipboard }:

# wrapGAppsHook4 is the canonical way to assemble GI_TYPELIB_PATH for a
# GTK4 program — it walks the propagated buildInputs and concatenates
# every transitive girepository-1.0 directory it finds (Pango, Cairo,
# PangoCairo, Graphene, libadwaita, …). We let it auto-wrap during
# fixupPhase instead of doing the makeWrapper dance ourselves so we
# don't have to maintain the typelib list by hand.

stdenvNoCC.mkDerivation {
  pname = "wayland-conky-widget-cli";
  version = "0.1.0";
  src = ../src/widget_cli;
  strictDeps = true;
  nativeBuildInputs = [ makeWrapper wrapGAppsHook4 gobject-introspection ];
  buildInputs = [ gtk4 libadwaita gtk4-layer-shell ];

  installPhase = ''
    runHook preInstall
    mkdir -p $out/{bin,lib/wayland_conky_cli}
    cp -r $src/* $out/lib/wayland_conky_cli/
    mkdir -p $out/lib/python
    ln -s $out/lib/wayland_conky_cli $out/lib/python/wayland_conky_cli
    makeWrapper ${pyEnv}/bin/python3 $out/bin/task-widget \
      --add-flags "-m wayland_conky_cli" \
      --prefix PYTHONPATH : "$out/lib/python" \
      --prefix PATH : ${fuzzel}/bin:${libnotify}/bin:${jq}/bin:${xdg-utils}/bin:${wl-clipboard}/bin
    runHook postInstall
  '';
}
