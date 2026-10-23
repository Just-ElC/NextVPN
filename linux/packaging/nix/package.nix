{
  lib,
  stdenv,
  meson,
  ninja,
  gettext,
  desktop-file-utils,
  appstream,
  wrapGAppsHook4,
  gobject-introspection,
  glib,
  gtk4,
  libadwaita,
  gsettings-desktop-schemas,
  librsvg,
  iproute2,
  python3,
  psiphon-tunnel-core,
  nextvpnSource,
}:

let
  pythonEnv = python3.withPackages (ps: [
    ps.pygobject3
    ps.pycairo
  ]);
in
stdenv.mkDerivation {
  pname = "nextvpn";
  version = "1.1.0";
  src = nextvpnSource;

  nativeBuildInputs = [
    meson
    ninja
    gettext
    desktop-file-utils
    appstream
    wrapGAppsHook4
    gobject-introspection
    pythonEnv
  ];

  buildInputs = [
    glib
    gtk4
    libadwaita
    # org.gnome.system.proxy, so the system proxy can be set on any desktop.
    gsettings-desktop-schemas
    # The tray and app icons are SVG.
    librsvg
    pythonEnv
  ];

  # The engine lives in its own store path and is referenced from there.
  mesonFlags = [ "-Dengine=${lib.getExe psiphon-tunnel-core}" ];

  # VPN mode reads the uplink with `ip`. nmcli is deliberately not added: it has
  # to be the one that matches the system's NetworkManager daemon.
  preFixup = ''
    gappsWrapperArgs+=(--suffix PATH : ${lib.makeBinPath [ iproute2 ]})
  '';

  doCheck = true;

  meta = {
    description = "Free internet in one click: a GTK client for the Psiphon network";
    longDescription = ''
      NextVPN for Linux. One button, no accounts, no traffic limits. Runs on the
      psiphon-tunnel-core engine and uses the same server network as NextVPN for
      Windows. With NetworkManager every program goes through the tunnel (VPN
      mode); without it, the GNOME and KDE system proxy is set while connected.
    '';
    homepage = "https://github.com/Just-ElC/NextVPN";
    # No licence is declared for NextVPN's own code yet; the engine (a separate
    # package) is GPL-3.0-only.
    mainProgram = "nextvpn";
    platforms = lib.platforms.linux;
  };
}
