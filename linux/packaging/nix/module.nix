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
    # VPN mode, which tunnels every program, asks NetworkManager for its
    # interface. No password and no extra rules are needed: NetworkManager's
    # polkit defaults let the desktop user do it, and the routing it sets up
    # passes the firewall's strict reverse-path check as it is.
    warnings = lib.optional (!config.networking.networkmanager.enable)
      "NextVPN: networking.networkmanager.enable is off, so only the system proxy mode works; programs that ignore it (most on Hyprland, Sway and other window managers) bypass the tunnel.";
    # Without dconf, GSettings keeps changes in memory and the GNOME-side system
    # proxy would never reach other applications. GNOME enables it already;
    # Plasma and window-manager setups often do not.
    programs.dconf.enable = lib.mkDefault true;
  };
}
