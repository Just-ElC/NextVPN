# NextVPN

A WinUI 3 client for the Psiphon circumvention network, built to replace the stock
Psiphon 3 Windows client's interface while keeping every bit of its tunnelling
behaviour.

The tunnel itself is `psiphon-tunnel-core`, the same open source engine the official
client uses. This project replaces only the interface and the process management
around it.

---

## Why this exists

Two reasons:

1. The stock client's interface is dated.
2. The stock client rewrites itself. It downloads `psiphon3.exe.upgrade`, and on the
   next launch renames the running binary to `psiphon3.exe.orig` and swaps a new one
   into place. It also extracts `psiphon-tunnel-core.exe` into `%TEMP%` on every run
   and deletes it on exit. That is where the disappearing files come from — nothing
   external is deleting them.

This client does neither. See [Self-modification, removed](#self-modification-removed).

---

## How it works

The official Windows client is a GUI wrapper around a console process, and this client
follows the same architecture, because it is the one the engine is designed for:

```
NextVPN.exe  ──spawns──>  engine\psiphon-tunnel-core.exe
     │                          │
     │   <── newline-delimited JSON "notices" on stderr ──┘
     │
     └── sets the WinINet system proxy to 127.0.0.1:<local HTTP port>
```

The engine opens a local SOCKS proxy and a local HTTP proxy on loopback, then tunnels
whatever is sent to them. Pointing Windows at the local HTTP proxy is what makes the
tunnel apply system-wide.

### The notice protocol

The engine reports everything as one JSON object per line on stderr:

```json
{"data":{"count":1},"noticeType":"Tunnels","timestamp":"..."}
{"data":{"port":57104},"noticeType":"ListeningHttpProxyPort","timestamp":"..."}
{"data":{"serverRegion":"DE"},"noticeType":"ConnectedServerRegion","timestamp":"..."}
{"data":{"diagnosticID":"wpHHqb3e","protocol":"INPROXY-WEBRTC-QUIC-OSSH"},"noticeType":"ActiveTunnel","timestamp":"..."}
```

`Tunnels.count > 0` is the authoritative "connected" signal. The notices this client
acts on are listed in [`Core/Notice.cs`](src/NextVpn/Core/Notice.cs).

### Configuration

`engine\base.config` carries the sponsor identity and crypto material —
`PropagationChannelId`, `SponsorId`, the server list signature keys, and the
`AdditionalParameters` blob. Those are passed through untouched.

[`Core/TunnelConfig.cs`](src/NextVpn/Core/TunnelConfig.cs) overlays only the fields
this client owns: egress region, local proxy ports, transport restrictions, upstream
proxy, and the data directory.

> One sharp edge worth recording: the engine's JSON parser rejects a UTF-8 byte order
> mark and fails with `invalid character 'ï' looking for beginning of value`. The
> config must be written as BOM-less UTF-8.

---

## Self-modification, removed

| Stock client | This client |
| --- | --- |
| Downloads `psiphon3.exe.upgrade`, renames the running binary to `.orig`, replaces itself | Never downloads or replaces any binary |
| Extracts `psiphon-tunnel-core.exe` to `%TEMP%`, deletes it on exit | Ships the engine in `engine\` and only ever reads it |
| `EnableUpgradeDownload: true` | Forced to `false`, and the upgrade URLs are stripped from the config entirely |

The strip list is enforced in code rather than left to configuration, in
`TunnelConfig.StrippedFields`. A `ClientUpgradeAvailable` notice from the network is
surfaced as information only.

### If Windows Defender is also removing it

Psiphon binaries are a long-standing false positive for several antivirus engines,
because obfuscated transports look like the thing they are designed to detect. If
Defender quarantines the engine, that is a separate matter from the self-replacement
above, and the fix is a Defender exclusion that you add yourself in
**Windows Security → Virus & threat protection → Manage settings → Exclusions**.

Nothing in this project attempts to evade or disable antivirus detection.

---

## Installing

Two downloads, both x64:

| | |
| --- | --- |
| `NextVPN-Setup-<version>.exe` | Installs for the current user |
| `NextVPN-<version>-win-x64.zip` | Portable: unpack anywhere and run `NextVPN.exe` |

Both need the [.NET 8 Desktop Runtime](https://dotnet.microsoft.com/download/dotnet/8.0/runtime)
(x64). The setup checks for it and offers the download page rather than failing at
launch.

The setup needs no administrator rights and touches exactly three places:

```
%LOCALAPPDATA%\Programs\NextVPN                       the application
Start Menu\Programs\NextVPN.lnk                       the shortcut
HKCU\...\CurrentVersion\Uninstall\NextVPN             the Installed apps entry
```

Settings live in `%LOCALAPPDATA%\NextVPN` and are left alone by the uninstaller. No
service, no scheduled task, no driver, nothing under `HKLM`, and nothing outside
those paths. "Launch when I sign in", if you turn it on, adds one `HKCU\...\Run`
value that the uninstaller removes again.

To remove it: **Settings → Apps → Installed apps → NextVPN → Uninstall**, or run
`NextVPN-Uninstall.exe --uninstall` from the install folder.

```
NextVPN-Setup.exe                install, asking first
NextVPN-Setup.exe --silent       install without asking
NextVPN-Setup.exe --dir=<path>   install somewhere else
NextVPN-Setup.exe --no-shortcut  skip the Start menu shortcut
NextVPN-Uninstall.exe --uninstall [--silent] [--purge]
```

`--purge` also deletes your settings. The uninstaller refuses to run while NextVPN
is open, and if a saved copy of your previous proxy settings is still on disk it
offers to start NextVPN once to put them back — removing the application first would
leave Windows pointing at a local port that no longer exists.

> The setup is not code signed, so SmartScreen will warn on first run: **More info →
> Run anyway**. Signing needs a certificate that costs money; the published SHA-256
> is the alternative if you want to check what you downloaded.

## Building

Only the .NET SDK is required. Visual Studio is not.

```powershell
.\build.ps1 -Publish
```

```powershell
.\build.ps1 -Test
```

Building a release — the setup, the portable zip and their SHA-256 sums, into
`dist\`:

```powershell
.\build.ps1 -Installer
```

The setup is the same program as the uninstaller, in `setup\NextVpn.Setup`: built
once with the application zip embedded as a resource, and once without, which is the
`NextVPN-Uninstall.exe` that ships inside the application folder. Both are
self-contained and trimmed, so the setup runs on a machine with no .NET installed —
which is exactly the machine that needs an installer.

Output lands in `dist\NextVPN\`, which is portable: copy the folder anywhere and run
`NextVPN.exe`. It needs the .NET 8 Desktop Runtime; the Windows App SDK is bundled.

### Building WinUI without Visual Studio

Worth writing down, because the failure mode is opaque. Windows App SDK 1.7 declares
its MSIX and PRI MSBuild tasks against assemblies that ship only with Visual Studio:

```
$(MSBuildExtensionsPath)\Microsoft\VisualStudio\v$(VisualStudioVersion)\AppxPackage\
```

With just the .NET SDK installed those are absent, and the build fails in two stages —
first `MSB4062` for the missing task assemblies, and before that `XamlCompiler.exe`
exits with code 1 and prints nothing at all.

The fix is two lines in the project file:

```xml
<PackageReference Include="Microsoft.Windows.SDK.BuildTools.MSIX" Version="1.7.*" GeneratePathProperty="true" />
...
<MsixTaskAssemblyLocation>$(PkgMicrosoft_Windows_SDK_BuildTools_MSIX)\tools\net6.0\</MsixTaskAssemblyLocation>
```

The package carries the tasks. The property override is needed because Windows App SDK
sets `MsixTaskAssemblyLocation` to a path inside itself where the assembly does not
exist, and the package's own default is guarded by an "if empty" condition that
therefore never fires.

---

## Tests

200 tests, xunit, about 50ms:

```powershell
.\build.ps1 -Test
```

The application is a WinUI executable, so a test project cannot reference it without
dragging in the XAML framework and a UI thread. Everything worth testing has no UI
dependency at all, so `tests/NextVpn.Tests` compiles those source files into its own
assembly with `<Compile Include="..\..\src\NextVpn\Core\*.cs" />`. Nothing is
duplicated: change a source file and these tests compile against the change.

What is covered, and why it is the part that matters:

| Area | What is pinned down |
| --- | --- |
| `TunnelConfig` | Every upgrade and migration field is stripped whether or not the base config asks for it, `EnableUpgradeDownload` is forced off, sponsor and crypto material passes through untouched, and the file is written without a byte order mark |
| `Notice` | Malformed lines, missing fields, numbers written as strings, counters too large for an `int` — none of it may throw, because the reader loop is what the connection state depends on |
| `TunnelTelemetry` | Recorded notice streams: first tunnel starts the clock, a mid-session redial pauses it without losing the totals, a zero count before anything connected is not a disconnection |
| `NoticePolicy` | Which notices are logged, and which are allowed to wake the UI thread |
| `Format` | Every number on the connection panel, at its boundaries |
| `StatusPresenter` | Every state produces a heading, a subtitle and an action label |
| `AppSettings` | Round trips, and that a damaged file yields defaults rather than a crash |
| `SystemProxy` | The proxy string the whole machine is pointed at |

Deliberately not covered: writing to the registry and to WinINet, starting the engine
process, and XAML layout. Those need a machine or a UI thread rather than a test, and
a test that changed this machine's proxy settings would be worse than no test.

## Interface

Built against the Fluent 2 specifications rather than by eye:

- **Two-layer structure.** The title bar and navigation sit on mica (the base layer);
  page content sits on `LayerFillColorDefaultBrush` with cards on top, each carrying
  the 1px contour Windows uses to express card elevation.
- **System brushes throughout.** `CardBackgroundFillColor*`, `TextFillColor*`,
  `CardStrokeColor*`. Only the brand accent is defined per theme, so light, dark and
  high contrast all track Windows instead of fighting it.
- **The Windows type ramp**, via `CaptionTextBlockStyle`, `BodyTextBlockStyle`,
  `BodyStrongTextBlockStyle`, `SubtitleTextBlockStyle` and `TitleTextBlockStyle` —
  no hand-picked font sizes. Sentence case, Semibold rather than Bold.

### One grid, one rhythm

The connection page is a single grid of three equal columns with a 12px gutter, and
every card starts and ends on a column edge:

```
┌───────────────────────────────────────────────┐
│                   connect                     │   hero, spans 3
└───────────────────────────────────────────────┘
┌───────────┐ ┌───────────┐ ┌───────────┐
│ downloaded│ │ uploaded  │ │ connected │           3 × 1
└───────────┘ └───────────┘ └───────────┘
┌───────────┐ ┌───────────────────────────┐
│   exit    │ │        throughput         │        1 + 2
└───────────┘ └───────────────────────────┘
┌───────────┐ ┌───────────┐ ┌───────────┐
│ your loc. │ │ local     │ │ system    │           3 × 1
└───────────┘ └───────────┘ └───────────┘
```

So the left edge of the exit card, the first statistic and the first detail are the
same line, and so are the right edges. The gutter, the card radius, the card padding
and the page padding are single resources in `App.xaml` (`Gutter`, `CardCorner`,
`CardPadding`, `PagePadding`), used by every page, so rows line up across pages as
well as within one.

The earlier version reflowed those two rows with `UniformGridLayout`, which sizes
columns from `MinItemWidth` rather than from the row: three items in a panel wide
enough for six left half the row empty, and the two rows did not agree on column
positions because they used different minimums.

### Adapting to the window

- Vertical: the throughput row is the star row, so spare height goes into the graph
  instead of collecting as dead space under the last card. The layout is made at least
  as tall as the viewport from the scroller's own `SizeChanged` — reading the viewport
  and writing the child, rather than binding one to the other, which measured forever.
- Horizontal: the exit and throughput cards sit side by side above 880px of content
  width and stack below it, and the status heading steps down a size when they do.

> The breakpoint is driven from the layout's own `SizeChanged`, not an `AdaptiveTrigger`.
> `AdaptiveTrigger.MinWindowWidth` measures the window, which includes the navigation
> pane, so it switched at the wrong content width.

### The connect control

Concentric circles on one centre: a static track, a rotating arc and two expanding
ripples while the engine is dialling, a radial glow whose strength follows the state,
and the button itself. Everything that moves is a composition animation, evaluated on
the compositor thread; the animation objects are built once and restarted, so a
tunnel that stays up for hours costs nothing. Nothing pulses once connected — a
permanent animation forces the compositor to redraw the window, mica included,
forever.

Two things about it are worth writing down, because both look like nothing being
wrong:

> **A stock `Button` cannot carry a gradient.** Its template replaces the background
> with `ButtonBackgroundPointerOver` and `ButtonBackgroundPressed` in those states, so
> the brand gradient turned flat grey the moment the pointer touched it. The control
> now has its own template in which the gradient is the face and the states are a
> scrim laid over it (`ConnectButton` in `App.xaml`). The focus ring is a circle for
> the same reason — the system focus visual is a rectangle, which around a disc looks
> like a mistake.

> **Visual states only work from the template's root element.** The exit-location
> card is also a templated button, and its states sat one element deeper than the
> template root. It parses, it builds, and the control never finds them, so hover and
> press produce nothing at all. Both custom templates were verified afterwards by
> measuring the rendered pixels rather than by looking at them.

> **Do not toggle `Visibility` on an element you animate through composition.** The
> ripples and the arc were declared `Visibility="Collapsed"` with `Opacity="0"` and
> switched to visible just before their animations started. XAML then pushed the
> element's own `Opacity` back onto the visual on the next layout pass, which cancels
> the composition animation silently: the rings were visible, fully transparent, and
> perfectly still. They are now never collapsed, only faded, and the animator owns the
> opacity outright.

### Why country codes and not flags

Windows ships no glyphs for regional-indicator pairs, so flag emoji render as bare
letters. Exits are drawn as a code badge instead.

---

## Layout

```
engine/                       engine binary, embedded server list, base config
src/NextVpn/
  Core/
    TunnelEngine.cs           process lifecycle and the connection state machine
    TunnelTelemetry.cs        what each notice means for the session
    TunnelConfig.cs           config generation, upgrade plumbing stripped
    Notice.cs                 notice protocol types
    NoticePolicy.cs           what is logged, and what may wake the UI thread
    StatusPresenter.cs        every word the connection panel says
    Format.cs                 every number it shows
    AppSettings.cs            persisted settings + every path the app uses
    Regions.cs                egress regions and transports
  Interop/
    SystemProxy.cs            WinINet proxy apply/revert, with crash recovery
    TrayIcon.cs               Shell_NotifyIcon, message-only window, context menu
    ProcessJob.cs             job object that kills the engine if the app is killed
    StartupTask.cs            optional HKCU run entry
  ViewModels/MainViewModel.cs binding surface
  Views/                      Home, Regions, Settings, Activity, ConnectAnimator
tests/NextVpn.Tests/          the suite described below
setup/NextVpn.Setup/          the setup program, which is also the uninstaller
```

State lives in `%LOCALAPPDATA%\NextVPN\`. Nothing is written next to the executable at
runtime.

### Proxy safety

The previous proxy settings are written to `%LOCALAPPDATA%\NextVPN\proxy-backup.json`
*before* they are changed. If the app is killed while connected, the next launch
detects that the system is still pointing at one of its own dead local ports and
restores the saved settings. A crash cannot leave the machine without working network.

---

## Licensing

`psiphon-tunnel-core` is developed by Psiphon Inc. and licensed under the GPLv3. It is
used here as a separate executable, invoked over a documented process interface. The
release ships that binary unmodified; its source is at
[Psiphon-Labs/psiphon-tunnel-core](https://github.com/Psiphon-Labs/psiphon-tunnel-core).

This client is an independent interface. It is not affiliated with, endorsed by, or
supported by Psiphon Inc. Bugs here are not their problem.
