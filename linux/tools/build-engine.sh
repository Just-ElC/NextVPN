#!/bin/sh
# Builds psiphon-tunnel-core's console client from source and puts it in
# linux/engine/ as psiphon-tunnel-core-<arch>, next to the bundled x86_64 one.
#
# Needs git and Go (the version psiphon-tunnel-core's go.mod asks for).
#
#   tools/build-engine.sh [revision]
set -eu

# The staging-client branch commit the bundled x86_64 binary was built from.
revision=${1:-c4a09096ab401b57f52e092c8f2f829c8fac7628}
here=$(cd "$(dirname "$0")/.." && pwd)
arch=$(uname -m)
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT

git init --quiet "$work/src"
git -C "$work/src" fetch --quiet --depth 1 https://github.com/Psiphon-Labs/psiphon-tunnel-core.git "$revision"
git -C "$work/src" checkout --quiet FETCH_HEAD

rev=$(git -C "$work/src" rev-parse --short=10 HEAD)
pkg=github.com/Psiphon-Labs/psiphon-tunnel-core/psiphon/common/buildinfo
ldflags="-s -w -X $pkg.buildDate=$(date -u +%Y-%m-%dT%H:%M:%SZ) \
 -X $pkg.buildRepo=https://github.com/Psiphon-Labs/psiphon-tunnel-core.git \
 -X $pkg.buildRev=$rev -X $pkg.goVersion=$(go env GOVERSION)"

cd "$work/src/ConsoleClient"
CGO_ENABLED=0 go build -mod=vendor -trimpath -ldflags "$ldflags" -o "$here/engine/psiphon-tunnel-core-$arch"

"$here/engine/psiphon-tunnel-core-$arch" -v
echo "Built $here/engine/psiphon-tunnel-core-$arch"
