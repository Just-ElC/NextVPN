# NixOS module:
#
#   imports = [ nextvpn.nixosModules.default ];
#   programs.nextvpn.enable = true;
self:
{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.programs.nextvpn;
in
{
  options.programs.nextvpn = {
    enable = lib.mkEnableOption "NextVPN, a GTK client for the Psiphon network";
    package = lib.mkOption {
      type = lib.types.package;
      default = self.packages.${pkgs.stdenv.hostPlatform.system}.nextvpn;
      defaultText = lib.literalExpression "nextvpn.packages.\${system}.nextvpn";
      description = "The NextVPN package to install.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ cfg.package ];
    # Without dconf, GSettings keeps changes in memory and the GNOME-side system
    # proxy would never reach other applications. GNOME enables it already;
    # Plasma and window-manager setups often do not.
    programs.dconf.enable = lib.mkDefault true;
  };
}
