{
  description = "Wayland-native conky widget for the task app, with fuzzel-driven CLI";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    let
      # The home-manager module lives outside the per-system block since
      # it's pure data + a config function. Consumers wire it into their
      # home.nix with `imports = [ inputs.wayland-conky.homeManagerModules.default ]`.
      homeModule = import ./modules/home.nix { inherit self; };
    in
    {
      homeManagerModules.default = homeModule;
      homeManagerModules.wayland-conky = homeModule;
    } // flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        py = pkgs.python3;
        # All Python deps the daemon + CLI need. Pinned via nixpkgs to
        # match whatever the user's NixOS channel ships; we don't carry
        # a separate lockfile.
        pyEnv = py.withPackages (ps: [
          ps.httpx
          ps.dateparser
          ps.tomli  # config.toml read
          ps.pygobject3  # GTK4 calendar popup
        ]);
      in
      {
        packages = {
          fetcher = pkgs.callPackage ./pkgs/fetcher.nix { inherit pyEnv; };
          widget-cli = pkgs.callPackage ./pkgs/widget-cli.nix { inherit pyEnv; };
          setup = pkgs.callPackage ./pkgs/setup.nix { };
          default = self.packages.${system}.widget-cli;
        };

        devShells.default = pkgs.mkShell {
          packages = [
            pyEnv
            pkgs.conky
            pkgs.fuzzel
            pkgs.jq
            pkgs.libnotify  # notify-send
            pkgs.wl-clipboard
            # The three binaries this repo produces. Put them on PATH so
            # `nix develop` is a one-shot test bench.
            self.packages.${system}.setup
            self.packages.${system}.fetcher
            self.packages.${system}.widget-cli
          ];
        };

        formatter = pkgs.nixpkgs-fmt;
      });
}
