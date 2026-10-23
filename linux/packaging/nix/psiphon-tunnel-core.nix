# The tunnel engine: Psiphon's console client at the revision NextVPN is tested
# with. On x86_64 this is the static build bundled in linux/engine/, byte for
# byte what every other distribution gets; elsewhere it is built from the same
# revision's source. `fromSource = true` builds it on x86_64 as well.
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
  rev = "b35028d7fde45fc2e42e66040c31ae582989b602";
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
    version = "0-unstable-2026-10-20-${shortRev}";
    src = "${nextvpnSource}/linux/engine";
    dontUnpack = true;
    # Fully static and already stripped: there is nothing to patch.
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
    version = "0-unstable-2026-10-20-${shortRev}";
    src = fetchgit {
      url = "https://github.com/Psiphon-Labs/psiphon-tunnel-core.git";
      inherit rev;
      hash = "sha256-/OAB2uc8Im1wbV7nsUabogrXA1Q+avc4J0wUQOWPEJc=";
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
        "-X ${pkg}.buildDate=2026-10-20T20:01:50Z"
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
