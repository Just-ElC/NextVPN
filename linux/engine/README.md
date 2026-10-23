# Tunnel engine for Linux

`psiphon-tunnel-core-x86_64` is Psiphon's console client for Linux, built
unmodified from
[psiphon-tunnel-core](https://github.com/Psiphon-Labs/psiphon-tunnel-core)
by `../tools/build-engine.sh`.

| | |
|---|---|
| Revision | `b35028d7fde45fc2e42e66040c31ae582989b602` (`master`, 2026-10-20) |
| Built with | Go 1.26.9 (the toolchain named in upstream `go.mod`), `CGO_ENABLED=0`, `-trimpath` |
| Linking | static — runs on any x86_64 distribution, NixOS included |
| SHA-256 | `4cdd2ae32d687bdbdf401042cde4c5647dd7332d720804792c5bd376d465a0c1` |
| Licence | GPLv3, source at the revision above |

It is newer than the last official binary
(`staging-client` `c4a09096ab`, 2026-10-05): it carries upstream's fixes from
19–20 October for in-proxy sessions, TLS ECH and IPv6 addresses on networks
without an IPv6 route.

It reads the same `engine/base.config` and `engine/server_list.dat` as the
Windows build, so both connect to the same servers with the same identity.

## Checking it against the source

The build is reproducible: the same revision and Go release give the same
bytes. CI rebuilds it on every pull request and fails if the result differs.
To check it yourself:

```sh
tools/build-engine.sh "" /tmp/psiphon-tunnel-core
sha256sum engine/psiphon-tunnel-core-x86_64 /tmp/psiphon-tunnel-core
```

## Other architectures

`../tools/build-engine.sh` with no arguments builds the same revision for the
machine it runs on and puts it here as `psiphon-tunnel-core-<arch>`. The Nix
flake does the same automatically on aarch64.

To use an engine installed elsewhere, set `NEXTVPN_ENGINE=/path/to/psiphon-tunnel-core`
or configure the build with `meson setup -Dengine=/path/to/psiphon-tunnel-core`.
