#!/bin/sh
# Builds the NextVPN RPM from this checkout.
#
#   sudo dnf install rpm-build meson gettext desktop-file-utils appstream gtk4-devel glib2-devel
#   linux/packaging/fedora/build-rpm.sh
#   sudo dnf install ~/rpmbuild/RPMS/x86_64/nextvpn-*.rpm
set -eu

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../../.." && pwd)
version=$(sed -n 's/^Version: *//p' "$here/nextvpn.spec")
top=$(rpm --eval '%{_topdir}')

mkdir -p "$top/SOURCES" "$top/SPECS"
# The working tree as it is, committed or not, so a local change can be tested.
tar -C "$root/.." --transform "s|^$(basename "$root")|NextVPN-$version|" \
    --exclude-vcs --exclude='__pycache__' --exclude='_build' \
    -czf "$top/SOURCES/NextVPN-$version.tar.gz" "$(basename "$root")"
cp "$here/nextvpn.spec" "$top/SPECS/"

rpmbuild -ba "$top/SPECS/nextvpn.spec"
echo
echo "Built:"
ls -1 "$top"/RPMS/*/nextvpn-"$version"-*.rpm
