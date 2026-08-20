using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Reflection;
using CommunityToolkit.Mvvm.ComponentModel;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using NextVpn.Core;
using NextVpn.Interop;
using NextVpn.ViewModels;

namespace NextVpn.Views;

/// <summary>One checkable transport in the settings list.</summary>
public sealed partial class ProtocolOption : ObservableObject
{
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public string Description { get; set; } = "";

    [ObservableProperty] private bool isSelected;

    public event EventHandler? SelectionChanged;

    partial void OnIsSelectedChanged(bool value) => SelectionChanged?.Invoke(this, EventArgs.Empty);
}

public sealed partial class SettingsPage : Page
{
    public MainViewModel ViewModel { get; } = App.ViewModel!;
    public AppSettings Settings => App.Settings;

    public ObservableCollection<ProtocolOption> Protocols { get; } = new();

    private bool _loading = true;

    public SettingsPage()
    {
        InitializeComponent();
        NavigationCacheMode = Microsoft.UI.Xaml.Navigation.NavigationCacheMode.Required;

        foreach (var p in TunnelProtocol.All)
        {
            var option = new ProtocolOption
            {
                Id = p.Id,
                Name = p.Name,
                Description = p.Description,
                IsSelected = Settings.LimitTunnelProtocols.Contains(p.Id)
            };
            option.SelectionChanged += OnProtocolChanged;
            Protocols.Add(option);
        }

        ThemeCombo.SelectedIndex = (int)Settings.Theme;

        // Keep the toggle honest if the startup entry was removed elsewhere.
        Settings.StartWithWindows = StartupTask.IsEnabled;

        Loaded += (_, _) => _loading = false;
    }

    // ------------------------------------------------------------- bindings

    public double HttpPortValue
    {
        get => Settings.LocalHttpProxyPort;
        set => Settings.LocalHttpProxyPort = ClampPort(value);
    }

    public double SocksPortValue
    {
        get => Settings.LocalSocksProxyPort;
        set => Settings.LocalSocksProxyPort = ClampPort(value);
    }

    private static int ClampPort(double value) =>
        double.IsNaN(value) ? 0 : Math.Clamp((int)value, 0, 65535);

    public string VersionText
    {
        get
        {
            var v = Assembly.GetExecutingAssembly().GetName().Version;
            return v is null ? "Version 1.0" : $"Version {v.Major}.{v.Minor}.{v.Build}";
        }
    }

    public string EngineText => EngineInfo.Value;

    /// <summary>Build banner from the tunnel engine, queried once and cached.</summary>
    private static readonly Lazy<string> EngineInfo = new(() =>
    {
        try
        {
            if (!File.Exists(Paths.TunnelCoreExe)) return "Tunnel engine: not found";

            using var proc = Process.Start(new ProcessStartInfo
            {
                FileName = Paths.TunnelCoreExe,
                Arguments = "-v",
                RedirectStandardError = true,
                RedirectStandardOutput = true,
                UseShellExecute = false,
                CreateNoWindow = true
            });
            if (proc is null) return "Tunnel engine: unavailable";

            var text = proc.StandardError.ReadToEnd() + proc.StandardOutput.ReadToEnd();
            if (!proc.WaitForExit(4000)) return "Tunnel engine: unavailable";

            var revision = Line(text, "Revision:");
            var built = Line(text, "Build Date:");
            var with = Line(text, "Built With:");
            return $"Tunnel engine: psiphon-tunnel-core {revision} ({with}), built {built}";
        }
        catch (Exception ex) when (ex is IOException or System.ComponentModel.Win32Exception or InvalidOperationException)
        {
            return "Tunnel engine: unavailable";
        }

        static string Line(string text, string prefix)
        {
            foreach (var raw in text.Split('\n'))
            {
                var line = raw.Trim();
                if (line.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                    return line[prefix.Length..].Trim();
            }
            return "unknown";
        }
    });

    // ------------------------------------------------------------- handlers

    private void OnProtocolChanged(object? sender, EventArgs e)
    {
        if (_loading) return;
        Settings.LimitTunnelProtocols = Protocols.Where(p => p.IsSelected).Select(p => p.Id).ToList();
        ViewModel.ApplyTunnelSettingChange();
    }

    /// <summary>Settings that take effect immediately, without touching the tunnel.</summary>
    private void OnSettingChanged(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        Settings.Save();
        ViewModel.NotifySettingsChanged();
    }

    /// <summary>Settings the engine only reads at startup, so the tunnel is rebuilt.</summary>
    private void OnReconnectingSettingChanged(object sender, RoutedEventArgs e)
    {
        if (_loading) return;
        ViewModel.ApplyTunnelSettingChange();
    }

    private void OnPortChanged(NumberBox sender, NumberBoxValueChangedEventArgs args)
    {
        if (_loading) return;
        ViewModel.ApplyTunnelSettingChange();
    }

    private void OnStartupToggled(object sender, RoutedEventArgs e)
    {
        if (_loading) return;

        if (!StartupTask.Set(Settings.StartWithWindows))
        {
            // Roll the toggle back if Windows refused the write.
            Settings.StartWithWindows = StartupTask.IsEnabled;
            if (sender is ToggleSwitch ts) ts.IsOn = Settings.StartWithWindows;
        }
        Settings.Save();
    }

    private void OnResetBypass(object sender, RoutedEventArgs e)
    {
        Settings.ProxyBypassList = AppSettings.DefaultBypassList;
        Settings.Save();
        Bindings.Update();
    }

    private void OnThemeChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loading) return;
        Settings.Theme = (AppTheme)ThemeCombo.SelectedIndex;
        Settings.Save();
        App.Window?.ApplyTheme(Settings.Theme);
    }

    private void OnOpenRegions(object sender, RoutedEventArgs e) => App.Window?.NavigateToRegions();

    private void OnOpenDataFolder(object sender, RoutedEventArgs e) => OpenFolder(Paths.DataDirectory);

    private void OnOpenEngineFolder(object sender, RoutedEventArgs e) => OpenFolder(Paths.EngineDirectory);

    private static void OpenFolder(string path)
    {
        try
        {
            Directory.CreateDirectory(path);
            Process.Start(new ProcessStartInfo { FileName = path, UseShellExecute = true });
        }
        catch (Exception ex) when (ex is IOException or System.ComponentModel.Win32Exception)
        {
        }
    }
}
