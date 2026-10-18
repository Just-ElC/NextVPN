# The tunnel engine: Psiphon's console client at the revision NextVPN is tested
# with. On x86_64 this is the official static build bundled in linux/engine/,
# byte for byte what every other distribution gets; elsewhere it is built from
# the same revision's source. `fromSource = true` builds it on x86_64 as well.
{
  lib,
  stdenvNoCC,
  buildGoModule,
  go,
  fetchgit,
  nextvpnSource,
  fromSource ? !stdenvNoCC.hostPlatform.isx86_64,
}:

let
  rev = "c4a09096ab401b57f52e092c8f2f829c8fac7628";
  shortRev = builtins.substring 0 10 rev;

  meta = {
    description = "Psiphon censorship circumvention engine (console client)";
    homepage = "https://github.com/Psiphon-Labs/psiphon-tunnel-core";
    license = lib.licenses.gpl3Only;
    mainProgram = "psiphon-tunnel-core";
    platforms = lib.platforms.linux;
  };

  bundled = stdenvNoCC.mkDerivation {
    pname = "psiphon-tunnel-core";
    version = "0-unstable-2026-10-05-${shortRev}";
    src = "${nextvpnSource}/linux/engine";
    dontUnpack = true;
    # UPX-packed and fully static: there is nothing to strip or patch, and
    # trying to would only damage it.
    dontStrip = true;
    dontPatchELF = true;
    installPhase = ''
      install -Dm755 "$src/psiphon-tunnel-core-x86_64" "$out/bin/psiphon-tunnel-core"
    '';
    meta = meta // {
      platforms = [ "x86_64-linux" ];
      sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
    };
  };

  built = buildGoModule {
    pname = "psiphon-tunnel-core";
    version = "0-unstable-2026-10-05-${shortRev}";
    src = fetchgit {
      url = "https://github.com/Psiphon-Labs/psiphon-tunnel-core.git";
      inherit rev;
      hash = "sha256-kTJs/KfdILL4cdKSGZ2bVgiR6UfExkseyDCymIjBvcI=";
    };
    # Dependencies are vendored upstream.
    vendorHash = null;
    subPackages = [ "ConsoleClient" ];
    env.CGO_ENABLED = 0;
    ldflags =
      let
        pkg = "github.com/Psiphon-Labs/psiphon-tunnel-core/psiphon/common/buildinfo";
      in
      [
        "-s"
        "-w"
        "-X ${pkg}.buildRepo=https://github.com/Psiphon-Labs/psiphon-tunnel-core.git"
        "-X ${pkg}.buildRev=${shortRev}"
        "-X ${pkg}.buildDate=2026-10-05T17:43:13+00:00"
        "-X ${pkg}.goVersion=go${go.version}"
      ];
    # The console client has no tests of its own; the library's need a network.
    doCheck = false;
    postInstall = ''
      mv "$out/bin/ConsoleClient" "$out/bin/psiphon-tunnel-core"
    '';
    inherit meta;
  };
in
if fromSource then built else bundled
