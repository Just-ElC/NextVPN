#!/bin/sh
# Builds the NextVPN RPM from this checkout.
#
#   sudo dnf install rpm-build meson gettext desktop-file-utils appstream gtk4-devel glib2-devel
#   linux/packaging/fedora/build-rpm.sh
#   sudo dnf install ~/rpmbuild/RPMS/x86_64/nextvpn-*.rpm
set -eu

here=$(cd "$(dirname "$0")" && pwd)
version=$(sed -n 's/^Version: *//p' "$here/nextvpn.spec")
top=$(rpm --eval '%{_topdir}')

mkdir -p "$top/SOURCES" "$top/SPECS"
"$here/../make-tarball.sh" "$top/SOURCES" >/dev/null
cp "$here/nextvpn.spec" "$top/SPECS/"

rpmbuild -ba "$top/SPECS/nextvpn.spec"
echo
echo "Built:"
ls -1 "$top"/RPMS/*/nextvpn-"$version"-*.rpm
