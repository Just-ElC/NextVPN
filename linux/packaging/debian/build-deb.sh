#!/bin/sh
# Builds nextvpn_<version>-1_amd64.deb for Ubuntu 24.04 and later, Debian 13
# and later, Linux Mint 22 and later: anything with libadwaita 1.4 or newer.
#
#   sudo apt install meson gettext dpkg-dev
#   linux/packaging/debian/build-deb.sh [output-dir]
#   sudo apt install ./nextvpn_*_amd64.deb
set -eu

root=$(cd "$(dirname "$0")/../../.." && pwd)
version=$(sed -n "s/^ *version: '\(.*\)',/\1/p" "$root/meson.build")
out=$(cd "${1:-.}" && pwd)
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT

meson setup "$work/build" "$root" --prefix=/usr --buildtype=plain -Dtests=false >/dev/null
meson compile -C "$work/build" >/dev/null
DESTDIR="$work/root" meson install -C "$work/build" --quiet

mkdir -p "$work/root/DEBIAN"
size=$(du -sk "$work/root" | cut -f1)
cat > "$work/root/DEBIAN/control" <<CONTROL
Package: nextvpn
Version: $version-1
Architecture: amd64
Maintainer: NextOS <https://github.com/Just-ElC/NextVPN/issues>
Installed-Size: $size
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, python3-cairo, gir1.2-gtk-4.0, gir1.2-adw-1 (>= 1.4), gsettings-desktop-schemas
Recommends: dconf-gsettings-backend | gsettings-backend
Section: net
Priority: optional
Homepage: https://github.com/Just-ElC/NextVPN
Description: Free internet in one click: a GTK client for the Psiphon network
 NextVPN for Linux. One button, no accounts, no traffic limits. Runs on the
 psiphon-tunnel-core engine and uses the same server network as NextVPN for
 Windows. Sets the GNOME and KDE system proxy while connected and puts the
 previous settings back afterwards.
CONTROL

deb="$out/nextvpn_${version}-1_amd64.deb"
dpkg-deb --build --root-owner-group "$work/root" "$deb" >/dev/null
echo "$deb"
