{
  description = "NextVPN for Linux: free internet in one click (GTK 4, Psiphon network)";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      packages = forAllSystems (pkgs: rec {
        psiphon-tunnel-core = pkgs.callPackage ./linux/packaging/nix/psiphon-tunnel-core.nix {
          nextvpnSource = self;
        };
        nextvpn = pkgs.callPackage ./linux/packaging/nix/package.nix {
          inherit psiphon-tunnel-core;
          nextvpnSource = self;
        };
        default = nextvpn;
      });

      apps = forAllSystems (pkgs: {
        default = {
          type = "app";
          program = nixpkgs.lib.getExe self.packages.${pkgs.stdenv.hostPlatform.system}.nextvpn;
        };
      });

      overlays.default = final: _prev: {
        nextvpn = self.packages.${final.stdenv.hostPlatform.system}.nextvpn;
      };

      nixosModules.default = import ./linux/packaging/nix/module.nix self;

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          inputsFrom = [ self.packages.${pkgs.stdenv.hostPlatform.system}.nextvpn ];
          packages = [ pkgs.go ];
        };
      });
    };
}
