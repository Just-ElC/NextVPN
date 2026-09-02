using System.Diagnostics;
using System.Text;
using NextVpn.Interop;

namespace NextVpn.Core;

public enum TunnelState
{
    Disconnected,
    Connecting,
    Connected,
    Disconnecting,
    Faulted
}

public sealed class TunnelStateChangedEventArgs(TunnelState state, string? detail = null) : EventArgs
{
    public TunnelState State { get; } = state;
    public string? Detail { get; } = detail;
}

public sealed class TunnelStats
{
    public long BytesSent { get; internal set; }
    public long BytesReceived { get; internal set; }
    public DateTimeOffset? ConnectedAt { get; internal set; }

    public TimeSpan Uptime => ConnectedAt is { } t ? DateTimeOffset.Now - t : TimeSpan.Zero;

    internal void Reset()
    {
        BytesSent = 0;
        BytesReceived = 0;
        ConnectedAt = null;
    }
}

/// <summary>
/// Owns the psiphon-tunnel-core child process and translates its notice stream
/// into state the UI can bind to.
///
/// The engine binary is launched from the application directory. It is never
/// copied to %TEMP%, never extracted at runtime and never deleted afterwards.
///
/// What each notice means lives in <see cref="TunnelTelemetry"/>; this class owns
/// only the process lifetime and the state machine around it.
/// </summary>
public sealed class TunnelEngine : IDisposable
{
    private readonly object _gate = new();
    private readonly ProcessJob _job = new();
    private readonly TunnelTelemetry _telemetry = new();
    private Process? _process;
    private CancellationTokenSource? _cts;
    private volatile bool _stopRequested;

    public TunnelState State { get; private set; } = TunnelState.Disconnected;

    public TunnelTelemetry Telemetry => _telemetry;
    public TunnelStats Stats => _telemetry.Stats;

    public int SocksPort => _telemetry.SocksPort;
    public int HttpPort => _telemetry.HttpPort;
    public string? ClientRegion => _telemetry.ClientRegion;
    public string? ConnectedRegion => _telemetry.ConnectedRegion;
    public string? ActiveProtocol => _telemetry.ActiveProtocol;
    public string? HomepageUrl => _telemetry.HomepageUrl;
    public IReadOnlyList<string> AvailableRegions => _telemetry.AvailableRegions;
    public string? UpgradeAvailableVersion => _telemetry.UpgradeAvailableVersion;

    public event EventHandler<TunnelStateChangedEventArgs>? StateChanged;
    public event EventHandler<Notice>? NoticeReceived;
    public event EventHandler? StatsUpdated;
    public event EventHandler? RegionsUpdated;

    public bool IsBusy => State is TunnelState.Connecting or TunnelState.Disconnecting;

    // ------------------------------------------------------------------ start

    public void Start(AppSettings settings)
    {
        lock (_gate)
        {
            if (_process is { HasExited: false }) return;

            if (!File.Exists(Paths.TunnelCoreExe))
            {
                Fault($"Tunnel engine not found at {Paths.TunnelCoreExe}");
                return;
            }
            if (!File.Exists(Paths.ServerListFile))
            {
                Fault($"Embedded server list not found at {Paths.ServerListFile}");
                return;
            }

            string configPath;
            try
            {
                configPath = TunnelConfig.Write(settings);
            }
            catch (Exception ex)
            {
                Fault($"Could not prepare tunnel configuration: {ex.Message}");
                return;
            }

            _telemetry.Reset();
            _stopRequested = false;
            SetState(TunnelState.Connecting);

            // An engine left behind by a previous hard kill still holds the datastore
            // lock, which would make this start fail with no obvious cause.
            KillOrphanedEngines();

            var psi = new ProcessStartInfo
            {
                FileName = Paths.TunnelCoreExe,
                WorkingDirectory = Paths.EngineDirectory,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardErrorEncoding = Encoding.UTF8,
                StandardOutputEncoding = Encoding.UTF8,
            };
            psi.ArgumentList.Add("--config");
            psi.ArgumentList.Add(configPath);
            psi.ArgumentList.Add("--serverList");
            psi.ArgumentList.Add(Paths.ServerListFile);

            try
            {
                _process = Process.Start(psi);
            }
            catch (Exception ex)
            {
                Fault($"Could not start the tunnel engine: {ex.Message}");
                return;
            }

            if (_process is null)
            {
                Fault("Could not start the tunnel engine.");
                return;
            }

            // Tie the engine's lifetime to this process at the kernel level, so it
            // cannot survive us even if we are terminated without running any code.
            _job.Add(_process);

            _cts = new CancellationTokenSource();
            var token = _cts.Token;
            var proc = _process;

            // Notices are newline-delimited JSON on stderr; stdout is drained so
            // a full pipe buffer can never stall the engine.
            _ = Task.Run(() => PumpAsync(proc.StandardError, token), token);
            _ = Task.Run(() => DrainAsync(proc.StandardOutput, token), token);
            _ = Task.Run(() => WatchExitAsync(proc), CancellationToken.None);
        }
    }

    // ------------------------------------------------------------------- stop

    public void Stop()
    {
        Process? proc;
        lock (_gate)
        {
            if (_process is null || _process.HasExited)
            {
                SetState(TunnelState.Disconnected);
                return;
            }
            _stopRequested = true;
            SetState(TunnelState.Disconnecting);
            proc = _process;
        }

        try
        {
            // tunnel-core has no Windows-native graceful shutdown signal, so the
            // process is terminated. Its BoltDB datastore is transactional and
            // survives an abrupt exit, which is how the stock client stops too.
            proc.Kill(entireProcessTree: true);
        }
        catch (Exception ex) when (ex is InvalidOperationException or System.ComponentModel.Win32Exception)
        {
            // Already gone.
        }
    }

    private async Task WatchExitAsync(Process proc)
    {
        try
        {
            await proc.WaitForExitAsync().ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is InvalidOperationException or SystemException)
        {
        }

        lock (_gate)
        {
            if (!ReferenceEquals(_process, proc)) return;

            _cts?.Cancel();
            _cts?.Dispose();
            _cts = null;
            try { _process?.Dispose(); } catch (InvalidOperationException) { }
            _process = null;

            // The local listeners died with the process; the session totals stay, so
            // the last screenful of numbers does not blank out on disconnect.
            _telemetry.ClearListeners();

            if (_stopRequested)
                SetState(TunnelState.Disconnected);
            else
                SetState(TunnelState.Faulted, "The tunnel engine stopped unexpectedly.");
        }
    }

    // ---------------------------------------------------------------- notices

    private async Task PumpAsync(StreamReader reader, CancellationToken token)
    {
        try
        {
            while (!token.IsCancellationRequested)
            {
                var line = await reader.ReadLineAsync(token).ConfigureAwait(false);
                if (line is null) break;
                if (Notice.TryParse(line, out var notice))
                    Handle(notice);
            }
        }
        catch (OperationCanceledException) { }
        catch (IOException) { }
        catch (ObjectDisposedException) { }
    }

    private static async Task DrainAsync(StreamReader reader, CancellationToken token)
    {
        try
        {
            while (!token.IsCancellationRequested && await reader.ReadLineAsync(token).ConfigureAwait(false) is not null)
            {
            }
        }
        catch (OperationCanceledException) { }
        catch (IOException) { }
        catch (ObjectDisposedException) { }
    }

    private void Handle(Notice n)
    {
        var signal = _telemetry.Apply(n);

        if (signal.HasFlag(TelemetrySignal.TunnelUp))
        {
            SetState(TunnelState.Connected);
        }
        else if (signal.HasFlag(TelemetrySignal.TunnelDown) && State == TunnelState.Connected)
        {
            // The engine redials by itself, so this is not the end of the session.
            SetState(TunnelState.Connecting);
        }

        if (signal.HasFlag(TelemetrySignal.RegionsChanged)) RegionsUpdated?.Invoke(this, EventArgs.Empty);
        if (signal.HasFlag(TelemetrySignal.StatsChanged)) StatsUpdated?.Invoke(this, EventArgs.Empty);

        NoticeReceived?.Invoke(this, n);
    }

    // ----------------------------------------------------------------- state

    private void SetState(TunnelState state, string? detail = null)
    {
        if (State == state && detail is null) return;
        State = state;
        StateChanged?.Invoke(this, new TunnelStateChangedEventArgs(state, detail));
    }

    private void Fault(string message)
    {
        SetState(TunnelState.Faulted, message);
    }

    /// <summary>
    /// Terminates engine processes started from our own engine directory that are no
    /// longer ours. Matching on the full executable path keeps this from touching any
    /// other Psiphon client the user may have running.
    /// </summary>
    private static void KillOrphanedEngines()
    {
        var ours = Path.GetFullPath(Paths.TunnelCoreExe);

        foreach (var p in Process.GetProcessesByName("psiphon-tunnel-core"))
        {
            try
            {
                var path = p.MainModule?.FileName;
                if (path is not null && string.Equals(Path.GetFullPath(path), ours, StringComparison.OrdinalIgnoreCase))
                    p.Kill(entireProcessTree: true);
            }
            catch (Exception ex) when (ex is InvalidOperationException
                                          or System.ComponentModel.Win32Exception
                                          or NotSupportedException)
            {
                // Another user's process, or it exited while we looked at it.
            }
            finally
            {
                p.Dispose();
            }
        }
    }

    public void Dispose()
    {
        Stop();
        _cts?.Cancel();
        _cts?.Dispose();
        _cts = null;
        try { _process?.Dispose(); } catch (InvalidOperationException) { }
        _process = null;
        _job.Dispose();
    }
}
