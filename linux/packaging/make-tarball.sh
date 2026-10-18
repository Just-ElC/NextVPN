#!/bin/sh
# Packs the sources of the Linux build into NextVPN-<version>-linux.tar.gz:
# everything under linux/, the shared engine files and the top-level meson and
# Nix files. The Windows sources and the Windows engine stay out.
#
#   linux/packaging/make-tarball.sh [output-dir]
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
version=$(sed -n "s/^ *version: '\(.*\)',/\1/p" "$root/meson.build")
out=$(cd "${1:-.}" && pwd)
name="NextVPN-$version"
archive="$out/$name-linux.tar.gz"

set -- README.md meson.build meson_options.txt flake.nix \
       engine/base.config engine/server_list.dat \
       .github/logo.png .github/screenshot-linux-light.png .github/screenshot-linux-dark.png \
       linux

if git -C "$root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  # Exactly the tracked files, so nothing left over from a local build slips in.
  git -C "$root" ls-files -z -- "$@" |
    tar -C "$root" --null -T - --transform "s|^|$name/|" -czf "$archive"
else
  tar -C "$root" --exclude='__pycache__' --exclude='_build' \
    --transform "s|^|$name/|" -czf "$archive" "$@"
fi
echo "$archive"
