{ stdenvNoCC, python3, makeWrapper }:

# setup is now stdlib-only (no Firebase Admin SDK) — the in-app
# Settings → API keys flow handles issuance, this script just stores
# the resulting plaintext token.
stdenvNoCC.mkDerivation {
  pname = "wayland-conky-setup";
  version = "0.1.0";
  src = ../scripts;
  nativeBuildInputs = [ makeWrapper ];
  installPhase = ''
    mkdir -p $out/{bin,lib}
    cp $src/setup.py $out/lib/setup.py
    makeWrapper ${python3}/bin/python3 $out/bin/wayland-conky-setup \
      --add-flags "$out/lib/setup.py"
  '';
}
