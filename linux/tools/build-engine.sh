#!/bin/sh
# Builds psiphon-tunnel-core's console client from source and puts it in
# linux/engine/ as psiphon-tunnel-core-<arch>.
#
# The build is reproducible: the same revision built with the same Go release
# gives the same bytes, so anyone can check the bundled binary against the
# source (CI does, on every pull request). Needs git and the Go release named by
# the toolchain line of psiphon-tunnel-core's go.mod.
#
#   tools/build-engine.sh [revision] [output]
set -eu

# The upstream master commit the bundled x86_64 binary was built from.
revision=${1:-b35028d7fde45fc2e42e66040c31ae582989b602}
here=$(cd "$(dirname "$0")/.." && pwd)
arch=$(uname -m)
out=${2:-$here/engine/psiphon-tunnel-core-$arch}
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT

git init --quiet "$work/src"
git -C "$work/src" fetch --quiet --depth 1 https://github.com/Psiphon-Labs/psiphon-tunnel-core.git "$revision"
git -C "$work/src" checkout --quiet FETCH_HEAD

rev=$(git -C "$work/src" rev-parse --short=10 HEAD)
# The commit's own time, not the clock: the build date is part of the binary.
date=$(TZ=UTC git -C "$work/src" log -1 --date=format-local:%Y-%m-%dT%H:%M:%SZ --format=%cd)

cd "$work/src/ConsoleClient"
# Inside the module, so a Go older than its toolchain line has already switched
# to (and reports) the release that actually does the build.
pkg=github.com/Psiphon-Labs/psiphon-tunnel-core/psiphon/common/buildinfo
ldflags="-s -w -buildid= -X $pkg.buildDate=$date \
 -X $pkg.buildRepo=https://github.com/Psiphon-Labs/psiphon-tunnel-core.git \
 -X $pkg.buildRev=$rev -X $pkg.goVersion=$(go env GOVERSION)"
CGO_ENABLED=0 GOFLAGS= go build -mod=vendor -trimpath -buildvcs=false -ldflags "$ldflags" -o "$out"

"$out" -v
sha256sum "$out"
