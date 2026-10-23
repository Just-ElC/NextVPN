#!/bin/sh
# Installs NextVPN for Linux from this checkout.
#
#   ./install.sh               for you only, into ~/.local (no root needed)
#   ./install.sh --system      for everyone, into /usr/local (asks for sudo)
#   ./install.sh --deps        install what is missing first (asks for sudo)
#   ./install.sh --uninstall   remove it again (add --system if installed that way)
#
# On NixOS use the flake instead: nix run github:Just-ElC/NextVPN
set -eu

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/.." && pwd)
prefix="$HOME/.local"
sudo=""
deps=0
uninstall=0

for arg in "$@"; do
  case "$arg" in
    --system) prefix=/usr/local; sudo=sudo ;;
    --prefix=*) prefix=${arg#--prefix=} ;;
    --deps) deps=1 ;;
    --uninstall) uninstall=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '\033[1m%s\033[0m\n' "$*"; }

# ------------------------------------------------------------- distribution

distro=unknown
if [ -r /etc/os-release ]; then
  . /etc/os-release
  case " ${ID:-} ${ID_LIKE:-} " in
    *" nixos "*) distro=nixos ;;
    *" fedora "*|*" rhel "*) distro=fedora ;;
    *" arch "*) distro=arch ;;
    *" debian "*|*" ubuntu "*) distro=debian ;;
    *" opensuse"*|*" suse "*) distro=suse ;;
  esac
fi

if [ "$distro" = nixos ]; then
  say "This is NixOS. Use the flake instead:"
  echo "  nix run github:Just-ElC/NextVPN"
  echo "or add it to your configuration (see linux/README.md)."
  exit 1
fi

case "$distro" in
  fedora) packages="python3-gobject python3-cairo gtk4 libadwaita gsettings-desktop-schemas iproute meson gettext"
          install_cmd="sudo dnf install -y $packages" ;;
  arch)   packages="python-gobject python-cairo gtk4 libadwaita gsettings-desktop-schemas iproute2 meson gettext"
          install_cmd="sudo pacman -S --needed --noconfirm $packages" ;;
  debian) packages="python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 gsettings-desktop-schemas iproute2 meson gettext"
          install_cmd="sudo apt-get install -y $packages" ;;
  suse)   packages="python3-gobject python3-gobject-cairo typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1 gsettings-desktop-schemas iproute2 meson gettext-tools"
          install_cmd="sudo zypper install -y $packages" ;;
  *)      packages="PyGObject, pycairo, GTK 4, libadwaita, meson, gettext"
          install_cmd="" ;;
esac

# ------------------------------------------------------------------ uninstall

if [ "$uninstall" = 1 ]; then
  say "Removing NextVPN from $prefix"
  "$prefix/bin/nextvpn" --quit 2>/dev/null || true
  $sudo rm -rf "$prefix/share/nextvpn" "$prefix/libexec/nextvpn"
  $sudo rm -f "$prefix/bin/nextvpn" \
    "$prefix/share/applications/io.github.just_elc.NextVPN.desktop" \
    "$prefix/share/metainfo/io.github.just_elc.NextVPN.metainfo.xml" \
    "$prefix/share/icons/hicolor/scalable/apps/io.github.just_elc.NextVPN.svg" \
    "$prefix/share/icons/hicolor/256x256/apps/io.github.just_elc.NextVPN.png" \
    "$prefix/share/icons/hicolor/scalable/status/nextvpn-tray-connected.svg" \
    "$prefix/share/icons/hicolor/scalable/status/nextvpn-tray-connecting.svg" \
    "$prefix/share/icons/hicolor/scalable/status/nextvpn-tray-disconnected.svg" \
    "$prefix"/share/locale/*/LC_MESSAGES/nextvpn.mo
  rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/io.github.just_elc.NextVPN.desktop"
  say "Done. Your settings are kept in ${XDG_CONFIG_HOME:-$HOME/.config}/nextvpn;"
  echo "delete that folder and ${XDG_DATA_HOME:-$HOME/.local/share}/nextvpn to remove them as well."
  exit 0
fi

# --------------------------------------------------------------- dependencies

missing=""
python3 - <<'EOF' 2>/dev/null || missing="runtime"
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk
import cairo
assert (Adw.get_major_version(), Adw.get_minor_version()) >= (1, 4)
EOF
for tool in meson ninja msgfmt; do
  command -v "$tool" >/dev/null 2>&1 || missing="$missing $tool"
done

if [ -n "$missing" ]; then
  if [ "$deps" = 1 ] && [ -n "$install_cmd" ]; then
    say "Installing dependencies"
    echo "  $install_cmd"
    $install_cmd
  else
    say "Some dependencies are missing ($missing)."
    if [ -n "$install_cmd" ]; then
      echo "Install them with:"
      echo "  $install_cmd"
      echo "or run this script again with --deps."
    else
      echo "Install: $packages"
    fi
    exit 1
  fi
fi

# --------------------------------------------------------------------- build

build="${XDG_CACHE_HOME:-$HOME/.cache}/nextvpn-build"
say "Building"
if [ -d "$build" ]; then
  meson setup --reconfigure "$build" "$root" --prefix="$prefix" -Dtests=false >/dev/null
else
  meson setup "$build" "$root" --prefix="$prefix" -Dtests=false >/dev/null
fi
meson compile -C "$build" >/dev/null

say "Installing into $prefix"
$sudo meson install -C "$build" --quiet

echo
say "NextVPN is installed."
echo "Start it from the applications menu, or run: $prefix/bin/nextvpn"
case ":$PATH:" in
  *":$prefix/bin:"*) ;;
  *) echo "($prefix/bin is not on your PATH; the menu entry works regardless.)" ;;
esac
case "${XDG_CURRENT_DESKTOP:-}" in *GNOME*)
  echo
  echo "GNOME shows tray icons only with the AppIndicator extension"
  echo "(Fedora: gnome-shell-extension-appindicator). Without it, closing the window quits NextVPN."
  ;;
esac
