using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.UI.Dispatching;
using NextVpn.Core;
using NextVpn.Interop;

namespace NextVpn.ViewModels;

public sealed class LogEntry
{
    public LogEntry() { }

    public LogEntry(DateTimeOffset time, NoticeLevel level, string type, string message)
    {
        Time = time;
        Level = level;
        Type = type;
        Message = message;
    }

    public DateTimeOffset Time { get; set; }
    public NoticeLevel Level { get; set; }
    public string Type { get; set; } = "";
    public string Message { get; set; } = "";

    public string TimeText => Time.ToLocalTime().ToString("HH:mm:ss");
}

/// <summary>One throughput reading, in bytes per second.</summary>
public readonly record struct RateSample(double Down, double Up);

public sealed partial class MainViewModel : ObservableObject
{
    private const int MaxLogEntries = 1500;
    private const int MaxRateSamples = 64;

    private readonly TunnelEngine _engine = new();
    private readonly DispatcherQueue _ui = DispatcherQueue.GetForCurrentThread();
    private readonly DispatcherQueueTimer _tick;

    public AppSettings Settings { get; }

    public MainViewModel(AppSettings settings)
    {
        Settings = settings;

        SetRegionQuietly(Regions.Describe(settings.EgressRegion));
        RebuildRegionList(Array.Empty<string>());

        _engine.StateChanged += OnStateChanged;
        _engine.NoticeReceived += OnNotice;
        _engine.StatsUpdated += OnStats;
        _engine.RegionsUpdated += OnRegions;

        // Runs only while a session is up: the uptime is the only thing it advances,
        // and outside a session there is nothing for it to count.
        _tick = _ui.CreateTimer();
        _tick.Interval = TimeSpan.FromSeconds(1);
        _tick.Tick += (_, _) => OnPropertyChanged(nameof(UptimeText));
    }

    // ------------------------------------------------------------------ state

    [ObservableProperty] private TunnelState state = TunnelState.Disconnected;
    [ObservableProperty] private string statusDetail = "";
    [ObservableProperty] private string? activeProtocol;
    [ObservableProperty] private string? clientRegion;
    [ObservableProperty] private string? connectedRegion;
    [ObservableProperty] private int socksPort;
    [ObservableProperty] private int httpPort;

    public bool IsConnected => State == TunnelState.Connected;
    public bool IsConnecting => State == TunnelState.Connecting;
    public bool IsIdle => State is TunnelState.Disconnected or TunnelState.Faulted;
    public bool IsBusy => State is TunnelState.Connecting or TunnelState.Disconnecting;
    public bool IsFaulted => State == TunnelState.Faulted && StatusDetail.Length > 0;

    /// <summary>True while the tunnel is either up or on its way up.</summary>
    public bool IsLive => StatusPresenter.IsLive(State);

    public string StatusText => StatusPresenter.Heading(State);
    public string StatusSubtitle => StatusPresenter.Subtitle(State, ConnectedRegion, StatusDetail);
    public string ActionLabel => StatusPresenter.ActionLabel(State);

    public string ProtocolText => ActiveProtocol is { Length: > 0 } p ? p : Format.Empty;
    public string PortsText => Format.Ports(HttpPort, SocksPort);
    public string ClientRegionText => Format.Country(ClientRegion);

    public string SystemProxyText => Settings.SetSystemProxy
        ? (_proxyApplied ? "Applied system-wide" : "Applies on connect")
        : "Off — configure apps manually";

    // ---------------------------------------------------------------- notices

    [ObservableProperty] private string? sponsorPageUrl;
    [ObservableProperty] private string? upgradeVersion;

    public bool HasSponsorPage => !string.IsNullOrEmpty(SponsorPageUrl);
    public bool HasUpgradeNotice => !string.IsNullOrEmpty(UpgradeVersion);

    public string UpgradeNoticeText =>
        $"Version {UpgradeVersion} exists upstream. Nothing was downloaded and no file here was changed.";

    partial void OnSponsorPageUrlChanged(string? value) => OnPropertyChanged(nameof(HasSponsorPage));

    partial void OnUpgradeVersionChanged(string? value)
    {
        OnPropertyChanged(nameof(HasUpgradeNotice));
        OnPropertyChanged(nameof(UpgradeNoticeText));
    }

    // ---------------------------------------------------------------- regions

    [ObservableProperty] private RegionInfo selectedRegion = RegionInfo.Best;

    private bool _suppressRegionSideEffects;

    public ObservableCollection<RegionInfo> AvailableRegions { get; } = new();

    partial void OnSelectedRegionChanged(RegionInfo value)
    {
        OnPropertyChanged(nameof(SelectedRegionDisplay));
        if (_suppressRegionSideEffects) return;
        if (Settings.EgressRegion == value.Code) return;

        Settings.EgressRegion = value.Code;
        Settings.Save();

        // A region change only takes effect on a fresh tunnel.
        if (State is TunnelState.Connected or TunnelState.Connecting)
            Reconnect();
    }

    private void SetRegionQuietly(RegionInfo region)
    {
        _suppressRegionSideEffects = true;
        SelectedRegion = region;
        _suppressRegionSideEffects = false;
    }

    public string SelectedRegionDisplay => SelectedRegion.Display;

    private void RebuildRegionList(IReadOnlyList<string> codes)
    {
        AvailableRegions.Clear();
        AvailableRegions.Add(RegionInfo.Best);
        foreach (var c in codes.OrderBy(Regions.NameOf, StringComparer.CurrentCulture))
            AvailableRegions.Add(Regions.Describe(c));

        // Keep the saved choice visible even before the engine reports the list.
        if (!SelectedRegion.IsBest && AvailableRegions.All(r => r.Code != SelectedRegion.Code))
            AvailableRegions.Add(SelectedRegion);

        var match = AvailableRegions.FirstOrDefault(r => r.Code == SelectedRegion.Code);
        if (match is not null && !ReferenceEquals(match, SelectedRegion))
            SetRegionQuietly(match);
    }

    // ------------------------------------------------------------------ rates

    private readonly List<RateSample> _rates = new();
    private DateTimeOffset _lastSampleAt = DateTimeOffset.MinValue;

    public IReadOnlyList<RateSample> RateHistory => _rates;
    public event EventHandler? RatesChanged;

    public string DownRateText => Format.Rate(_rates.Count > 0 ? _rates[^1].Down : 0);
    public string UpRateText => Format.Rate(_rates.Count > 0 ? _rates[^1].Up : 0);

    private void RecordRate(long deltaDown, long deltaUp)
    {
        var now = DateTimeOffset.Now;
        var seconds = _lastSampleAt == DateTimeOffset.MinValue ? 1.0 : (now - _lastSampleAt).TotalSeconds;
        _lastSampleAt = now;
        if (seconds <= 0.05) seconds = 0.05;

        _rates.Add(new RateSample(deltaDown / seconds, deltaUp / seconds));
        while (_rates.Count > MaxRateSamples) _rates.RemoveAt(0);

        RatesChanged?.Invoke(this, EventArgs.Empty);
        OnPropertyChanged(nameof(DownRateText));
        OnPropertyChanged(nameof(UpRateText));
    }

    private void ClearRates()
    {
        _rates.Clear();
        _lastSampleAt = DateTimeOffset.MinValue;
        RatesChanged?.Invoke(this, EventArgs.Empty);
        OnPropertyChanged(nameof(DownRateText));
        OnPropertyChanged(nameof(UpRateText));
    }

    // ------------------------------------------------------------------ stats

    public string DownloadText => Format.Bytes(_engine.Stats.BytesReceived);
    public string UploadText => Format.Bytes(_engine.Stats.BytesSent);
    public string UptimeText => Format.Duration(_engine.Stats.Uptime);

    // -------------------------------------------------------------------- log

    public ObservableCollection<LogEntry> Log { get; } = new();

    [ObservableProperty] private bool showDiagnostics;

    // --------------------------------------------------------------- commands

    /// <summary>
    /// False only while the engine is being torn down: it cannot be restarted until
    /// its process has actually gone, so the control disables itself rather than
    /// accepting a press that would do nothing.
    /// </summary>
    public bool CanToggle => StatusPresenter.CanToggle(State);

    [RelayCommand(CanExecute = nameof(CanToggle))]
    private void Toggle()
    {
        if (StatusPresenter.IsLive(State)) Disconnect();
        else Connect();
    }

    [RelayCommand]
    public void Connect()
    {
        if (State is TunnelState.Connected or TunnelState.Connecting) return;
        SponsorPageUrl = null;
        ClearRates();
        AppendLog(NoticeLevel.Info, "Client", "Starting tunnel");
        _engine.Start(Settings);
    }

    [RelayCommand]
    private void Disconnect()
    {
        if (State is TunnelState.Disconnected) return;
        AppendLog(NoticeLevel.Info, "Client", "Stopping tunnel");
        _engine.Stop();
    }

    /// <summary>
    /// Restarts the tunnel so a changed setting takes effect. Guarded so that two
    /// quick changes in a row cannot race into two engine processes.
    /// </summary>
    private bool _restartPending;

    private void Reconnect()
    {
        if (_restartPending) return;
        _restartPending = true;

        _engine.Stop();

        _ = Task.Run(async () =>
        {
            for (var i = 0; i < 100 && _engine.State != TunnelState.Disconnected; i++)
                await Task.Delay(100).ConfigureAwait(false);

            _ui.TryEnqueue(() =>
            {
                _restartPending = false;
                if (State != TunnelState.Connected) _engine.Start(Settings);
            });
        });
    }

    [RelayCommand]
    private void ClearLog() => Log.Clear();

    // ---------------------------------------------------------- engine events

    private void OnStateChanged(object? sender, TunnelStateChangedEventArgs e) => _ui.TryEnqueue(() =>
    {
        State = e.State;
        StatusDetail = e.Detail ?? "";

        SocksPort = _engine.SocksPort;
        HttpPort = _engine.HttpPort;
        ActiveProtocol = _engine.ActiveProtocol;
        ConnectedRegion = _engine.ConnectedRegion;

        if (e.Detail is { Length: > 0 })
            AppendLog(e.State == TunnelState.Faulted ? NoticeLevel.Error : NoticeLevel.Info, "Client", e.Detail);

        if (State is TunnelState.Disconnected or TunnelState.Faulted) ClearRates();

        // The clock only has something to count while a session is up.
        if (State == TunnelState.Connected) _tick.Start();
        else _tick.Stop();

        ApplyOrRevertProxy();
        RaiseDerived();
    });

    private void OnStats(object? sender, EventArgs e) => _ui.TryEnqueue(() =>
    {
        OnPropertyChanged(nameof(DownloadText));
        OnPropertyChanged(nameof(UploadText));
    });

    private void OnRegions(object? sender, EventArgs e) =>
        _ui.TryEnqueue(() => RebuildRegionList(_engine.AvailableRegions));

    /// <summary>
    /// Runs on the engine's reader thread. Notices arrive in bursts of hundreds while
    /// a tunnel is being established, and most of them change nothing the user can
    /// see, so the decision to involve the UI thread at all is made here rather than
    /// inside a dispatched callback.
    /// </summary>
    private void OnNotice(object? sender, Notice n)
    {
        var verbose = ShowDiagnostics;
        if (!NoticePolicy.NeedsUi(n.Type, verbose)) return;

        var level = NoticePolicy.LevelOf(n.Type);
        var shouldLog = NoticePolicy.ShouldLog(n.Type, verbose);

        _ui.TryEnqueue(() => Apply(n, level, shouldLog));
    }

    private void Apply(Notice n, NoticeLevel level, bool shouldLog)
    {
        switch (n.Type)
        {
            case NoticeType.ClientRegion:
                ClientRegion = _engine.ClientRegion;
                OnPropertyChanged(nameof(ClientRegionText));
                break;

            case NoticeType.ActiveTunnel:
                ActiveProtocol = _engine.ActiveProtocol;
                OnPropertyChanged(nameof(ProtocolText));
                break;

            case NoticeType.ConnectedServerRegion:
                ConnectedRegion = _engine.ConnectedRegion;
                OnPropertyChanged(nameof(StatusSubtitle));
                break;

            case NoticeType.ListeningHttpProxyPort:
            case NoticeType.ListeningSocksProxyPort:
                SocksPort = _engine.SocksPort;
                HttpPort = _engine.HttpPort;
                OnPropertyChanged(nameof(PortsText));
                ApplyOrRevertProxy();
                break;

            case NoticeType.Homepage:
                SponsorPageUrl = n.String("url");
                break;

            case NoticeType.ClientUpgradeAvailable:
                // Reported only. Nothing is downloaded and no binary is replaced.
                UpgradeVersion = n.String("version");
                break;

            case NoticeType.BytesTransferred:
                // "received" is inbound, "sent" is outbound: down first, then up.
                RecordRate(n.Long("received") ?? 0, n.Long("sent") ?? 0);
                break;
        }

        if (shouldLog) AppendLog(level, n.Type, n.Message);
    }

    private void AppendLog(NoticeLevel level, string type, string message)
    {
        Log.Add(new LogEntry(DateTimeOffset.Now, level, type, message));
        while (Log.Count > MaxLogEntries) Log.RemoveAt(0);
    }

    // ------------------------------------------------------------------ proxy

    private bool _proxyApplied;

    private void ApplyOrRevertProxy()
    {
        var shouldApply = Settings.SetSystemProxy && State == TunnelState.Connected && HttpPort > 0;

        if (shouldApply && !_proxyApplied)
        {
            if (SystemProxy.Apply(HttpPort, SocksPort, Settings.ProxyBypassList))
            {
                _proxyApplied = true;
                AppendLog(NoticeLevel.Info, "Client",
                    $"System proxy set to {SystemProxy.BuildProxyString(HttpPort, SocksPort)}");
            }
            else
            {
                AppendLog(NoticeLevel.Warning, "Client", "Could not set the system proxy");
            }
        }
        else if (!shouldApply && _proxyApplied)
        {
            SystemProxy.Revert();
            _proxyApplied = false;
            AppendLog(NoticeLevel.Info, "Client", "System proxy restored");
        }

        OnPropertyChanged(nameof(SystemProxyText));
    }

    private void RaiseDerived()
    {
        OnPropertyChanged(nameof(IsConnected));
        OnPropertyChanged(nameof(IsConnecting));
        OnPropertyChanged(nameof(IsIdle));
        OnPropertyChanged(nameof(IsBusy));
        OnPropertyChanged(nameof(IsLive));
        OnPropertyChanged(nameof(IsFaulted));
        OnPropertyChanged(nameof(CanToggle));
        OnPropertyChanged(nameof(StatusText));
        OnPropertyChanged(nameof(StatusSubtitle));
        OnPropertyChanged(nameof(ActionLabel));
        OnPropertyChanged(nameof(ProtocolText));
        OnPropertyChanged(nameof(PortsText));
        OnPropertyChanged(nameof(UptimeText));
        OnPropertyChanged(nameof(ClientRegionText));
        OnPropertyChanged(nameof(SystemProxyText));
        ToggleCommand.NotifyCanExecuteChanged();
    }

    /// <summary>
    /// Called when the settings page changes something the live session cares about,
    /// so the system proxy follows the new preference without a reconnect.
    /// </summary>
    public void NotifySettingsChanged()
    {
        ApplyOrRevertProxy();
        RaiseDerived();
    }

    /// <summary>
    /// For settings the engine only reads at startup. Saves them and rebuilds the
    /// tunnel if one is up, so the change is not silently ignored until next launch.
    /// </summary>
    public void ApplyTunnelSettingChange()
    {
        Settings.Save();
        if (State is TunnelState.Connected or TunnelState.Connecting)
        {
            AppendLog(NoticeLevel.Info, "Client", "Rebuilding the tunnel to apply a changed setting");
            Reconnect();
        }
    }

    public void Shutdown()
    {
        _tick.Stop();
        if (_proxyApplied)
        {
            SystemProxy.Revert();
            _proxyApplied = false;
        }
        _engine.Dispose();
    }
}
