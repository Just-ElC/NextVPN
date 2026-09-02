<#
    Builds, tests and packages NextVPN.

    Requires only the .NET SDK - no Visual Studio. The MSIX/PRI MSBuild tasks that
    WinUI needs normally ship with VS; the project pulls them from the
    Microsoft.Windows.SDK.BuildTools.MSIX package instead and redirects
    MsixTaskAssemblyLocation at it.

    Usage:
        .\build.ps1              # build
        .\build.ps1 -Test        # run the test suite
        .\build.ps1 -Publish     # build a portable folder in .\dist\NextVPN
        .\build.ps1 -Installer   # build the release: setup .exe and portable .zip
        .\build.ps1 -Run         # build then launch
#>
[CmdletBinding()]
param(
    [switch]$Publish,
    [switch]$Run,
    [switch]$Test,
    [switch]$Installer,
    [string]$Configuration = 'Release'
)

$ErrorActionPreference = 'Stop'
$root    = $PSScriptRoot
$project = Join-Path $root 'src\NextVpn\NextVpn.csproj'
$tests   = Join-Path $root 'tests\NextVpn.Tests\NextVpn.Tests.csproj'
$setup   = Join-Path $root 'setup\NextVpn.Setup\NextVpn.Setup.csproj'

# Prefer a user-scope SDK if one is present, otherwise whatever is on PATH.
$dotnet = Join-Path $env:USERPROFILE '.dotnet\dotnet.exe'
if (-not (Test-Path $dotnet)) { $dotnet = 'dotnet' }

function Get-AppVersion {
    $text = Get-Content $project -Raw
    $match = [regex]::Match($text, '<Version>([^<]+)</Version>')
    if ($match.Success) { return $match.Groups[1].Value }
    return '1.0.0'
}

if ($Test) {
    # The tests compile the testable sources into their own assembly rather than
    # referencing the app, so they need neither WinUI nor a UI thread.
    & $dotnet test $tests --nologo
    if ($LASTEXITCODE -ne 0) { throw "tests failed" }
    if (-not ($Publish -or $Run -or $Installer)) { return }
}

if (-not (Test-Path (Join-Path $root 'engine\psiphon-tunnel-core.exe'))) {
    throw "engine\psiphon-tunnel-core.exe is missing. See README.md for what belongs in engine\."
}

if ($Installer) {
    $version = Get-AppVersion
    $dist    = Join-Path $root 'dist'
    $app     = Join-Path $dist 'NextVPN'
    $staging = Join-Path $root 'build'
    $payload = Join-Path $staging 'payload.zip'

    # 1. The application itself.
    & $dotnet publish $project -c $Configuration -r win-x64 --self-contained false -o $app
    if ($LASTEXITCODE -ne 0) { throw "publish failed" }

    New-Item -ItemType Directory -Force -Path $staging | Out-Null

    # 2. The uninstaller: the same setup program built without a payload, shipped
    #    inside the application folder so Installed apps has something to call.
    $uninstallOut = Join-Path $staging 'uninstall'
    & $dotnet publish $setup -c $Configuration -r win-x64 -o $uninstallOut `
        -p:BaseIntermediateOutputPath=../../build/obj-uninstall/
    if ($LASTEXITCODE -ne 0) { throw "uninstaller build failed" }
    Copy-Item (Join-Path $uninstallOut 'NextVPN-Setup.exe') (Join-Path $app 'NextVPN-Uninstall.exe') -Force

    # 3. One zip, used both as the installer payload and as the portable download.
    if (Test-Path $payload) { Remove-Item $payload -Force }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $app, $payload, [System.IO.Compression.CompressionLevel]::Optimal, $false)

    # 4. The setup, with that zip embedded.
    $setupOut = Join-Path $staging 'setup'
    & $dotnet publish $setup -c $Configuration -r win-x64 -o $setupOut `
        -p:PayloadZip=$payload -p:BaseIntermediateOutputPath=../../build/obj-setup/
    if ($LASTEXITCODE -ne 0) { throw "setup build failed" }

    $setupExe = Join-Path $dist "NextVPN-Setup-$version.exe"
    $portable = Join-Path $dist "NextVPN-$version-win-x64.zip"
    Copy-Item (Join-Path $setupOut 'NextVPN-Setup.exe') $setupExe -Force
    Copy-Item $payload $portable -Force

    $setupSize    = '{0:N1} MB' -f ((Get-Item $setupExe).Length / 1MB)
    $portableSize = '{0:N1} MB' -f ((Get-Item $portable).Length / 1MB)

    Write-Host ""
    Write-Host "Release $version" -ForegroundColor Green
    Write-Host "  $setupExe  ($setupSize)"
    Write-Host "  $portable  ($portableSize)"
    Write-Host ""
    Write-Host "  sha256:" -ForegroundColor DarkGray
    foreach ($file in @($setupExe, $portable)) {
        $hash = (Get-FileHash $file -Algorithm SHA256).Hash.ToLower()
        Write-Host ("    {0}  {1}" -f $hash, (Split-Path $file -Leaf)) -ForegroundColor DarkGray
    }

    if (-not $Run) { return }
    $exe = Join-Path $app 'NextVPN.exe'
}
elseif ($Publish) {
    $out = Join-Path $root 'dist\NextVPN'
    & $dotnet publish $project -c $Configuration -r win-x64 --self-contained false -o $out
    if ($LASTEXITCODE -ne 0) { throw "publish failed" }
    Write-Host "`nPortable build: $out" -ForegroundColor Green
    $exe = Join-Path $out 'NextVPN.exe'
} else {
    & $dotnet build $project -c $Configuration
    if ($LASTEXITCODE -ne 0) { throw "build failed" }
    $exe = Join-Path $root "src\NextVpn\bin\$Configuration\net8.0-windows10.0.19041.0\win-x64\NextVPN.exe"
}

if ($Run) { Start-Process $exe }
