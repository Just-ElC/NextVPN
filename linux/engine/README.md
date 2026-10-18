# Tunnel engine for Linux

`psiphon-tunnel-core-x86_64` is the official Psiphon console client for Linux,
unmodified, from
[Psiphon-Labs/psiphon-tunnel-core-binaries](https://github.com/Psiphon-Labs/psiphon-tunnel-core-binaries)
(`linux/psiphon-tunnel-core-x86_64`, commit `33ff79e89260f3adf92e846b96b3369b86a819d8`).

| | |
|---|---|
| Revision | `c4a09096ab` of [psiphon-tunnel-core](https://github.com/Psiphon-Labs/psiphon-tunnel-core) |
| Built | 2026-10-05, Go 1.26.8 |
| Linking | static (UPX-packed) — runs on any x86_64 distribution, NixOS included |
| SHA-256 | `046ca168da25d2c0e61c1c15e2b73bfbb67f5208112a4c94fe58fc5aab784f19` |
| Licence | GPLv3, source at the revision above |

It is the same engine the Windows build ships as `engine/psiphon-tunnel-core.exe`,
and it reads the same `engine/base.config` and `engine/server_list.dat`, so both
builds connect to the same servers with the same identity.

Do not strip it: it is UPX-packed, and `strip` refuses or corrupts such files.

## Other architectures, or building it yourself

`../tools/build-engine.sh` builds the console client from source with Go and
puts the result here as `psiphon-tunnel-core-<arch>`. The Nix flake does the same
automatically on aarch64.

To use an engine installed elsewhere, set `NEXTVPN_ENGINE=/path/to/psiphon-tunnel-core`
or configure the build with `meson setup -Dengine=/path/to/psiphon-tunnel-core`.
