{ stdenvNoCC, pyEnv, makeWrapper }:

stdenvNoCC.mkDerivation {
  pname = "wayland-conky-fetcher";
  version = "0.1.0";
  src = ../src/fetcher;
  nativeBuildInputs = [ makeWrapper ];
  installPhase = ''
    mkdir -p $out/{bin,lib/wayland-conky-fetcher}
    cp -r $src/* $out/lib/wayland-conky-fetcher/
    makeWrapper ${pyEnv}/bin/python3 $out/bin/wayland-conky-fetcher \
      --add-flags "$out/lib/wayland-conky-fetcher/main.py"
  '';
}
