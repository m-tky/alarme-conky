{ stdenvNoCC, python3, makeWrapper }:

let
  # Setup needs firebase-admin to mint custom tokens via the service
  # account; the rest is stdlib.
  pyEnv = python3.withPackages (ps: [ ps.firebase-admin ]);
in
stdenvNoCC.mkDerivation {
  pname = "wayland-conky-setup";
  version = "0.1.0";
  src = ../scripts;
  nativeBuildInputs = [ makeWrapper ];
  installPhase = ''
    mkdir -p $out/{bin,lib}
    cp $src/setup.py $out/lib/setup.py
    makeWrapper ${pyEnv}/bin/python3 $out/bin/wayland-conky-setup \
      --add-flags "$out/lib/setup.py"
  '';
}
