#!/bin/sh
# Runs NextVPN straight from a source checkout, no build step needed.
# Uses the engine in linux/engine/ and the shared files in engine/.
here=$(cd "$(dirname "$0")" && pwd)
export NEXTVPN_LAUNCHER="$here/run.sh"
export PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m nextvpn "$@"
