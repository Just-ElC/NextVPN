using System.Runtime.InteropServices;
using Microsoft.UI;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Animation;
using NextVpn.Core;
using NextVpn.Interop;
using NextVpn.ViewModels;
using NextVpn.Views;
using Windows.Graphics;

namespace NextVpn;

public sealed partial class MainWindow : Window
{
    public MainViewModel ViewModel { get; } = App.ViewModel!;

    private readonly TrayIcon? _tray;
    private bool _reallyClosing;
    private TunnelState _lastNotifiedState = TunnelState.Disconnected;

    // Dragging a window edge raises a change event per pixel. Without this the
    // settings file was rewritten hundreds of times during a single resize.
    private readonly DispatcherQueueTimer _geometryDebounce;

    // Four fixed status colours, allocated once rather than per state change.
    private static readonly SolidColorBrush ConnectedBrush = new(Windows.UI.Color.FromArgb(255, 46, 230, 168));
    private static readonly SolidColorBrush BusyBrush = new(Windows.UI.Color.FromArgb(255, 242, 180, 65));
    private static readonly SolidColorBrush FaultBrush = new(Windows.UI.Color.FromArgb(255, 255, 107, 107));
    private static readonly SolidColorBrush IdleBrush = new(Windows.UI.Color.FromArgb(255, 138, 143, 152));

    public MainWindow()
    {
        InitializeComponent();

        Title = "NextVPN";
        SystemBackdrop = new MicaBackdrop { Kind = Microsoft.UI.Composition.SystemBackdrops.MicaKind.BaseAlt };

        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);

        AppWindow.SetIcon(Path.Combine(Paths.AppDirectory, "Assets", "app.ico"));

        // Minimums must be set before the size is applied: setting them afterwards
        // snaps the window down to the minimum instead of leaving it as resized.
        // Deliberately below the 880 adaptive breakpoint, so the stacked layout is
        // actually reachable by resizing rather than being dead markup.
        if (AppWindow.Presenter is OverlappedPresenter presenter)
        {
            presenter.PreferredMinimumWidth = 560;
            presenter.PreferredMinimumHeight = 520;
        }

        RestoreGeometry();

        ApplyTheme(App.Settings.Theme);

        _geometryDebounce = DispatcherQueue.CreateTimer();
        _geometryDebounce.Interval = TimeSpan.FromMilliseconds(600);
        _geometryDebounce.IsRepeating = false;
        _geometryDebounce.Tick += (_, _) => SaveGeometry();

        _tray = new TrayIcon();
        if (_tray.IsAvailable) _tray.Command += OnTrayCommand;

        AppWindow.Closing += OnAppWindowClosing;
        AppWindow.Changed += OnAppWindowChanged;
        Closed += OnClosed;

        ViewModel.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName is nameof(MainViewModel.State) or nameof(MainViewModel.StatusText))
                OnStateChanged();
        };

        UpdateStatusPill();
        _tray?.SetState(ViewModel.State);

        ContentFrame.Navigate(typeof(HomePage), null, new EntranceNavigationTransitionInfo());
    }

    // ------------------------------------------------------------------ theme

    public void ApplyTheme(AppTheme theme)
    {
        var requested = theme switch
        {
            AppTheme.Light => ElementTheme.Light,
            AppTheme.Dark => ElementTheme.Dark,
            _ => ElementTheme.Default
        };

        if (RootGrid is FrameworkElement root) root.RequestedTheme = requested;

        // The caption buttons are drawn by the system and do not follow RequestedTheme,
        // so they are tinted explicitly to match the rest of the window.
        var bar = AppWindow.TitleBar;
        bar.ExtendsContentIntoTitleBar = true;
        bar.ButtonBackgroundColor = Colors.Transparent;
        bar.ButtonInactiveBackgroundColor = Colors.Transparent;

        var dark = requested == ElementTheme.Dark ||
                   (requested == ElementTheme.Default && Application.Current.RequestedTheme == ApplicationTheme.Dark);

        bar.ButtonForegroundColor = dark ? Colors.White : Colors.Black;
        bar.ButtonHoverForegroundColor = dark ? Colors.White : Colors.Black;
        bar.ButtonInactiveForegroundColor = dark ? Colors.Gray : Colors.DimGray;
        bar.ButtonHoverBackgroundColor = dark
            ? Windows.UI.Color.FromArgb(24, 255, 255, 255)
            : Windows.UI.Color.FromArgb(20, 0, 0, 0);
    }

    // ----------------------------------------------------------------- status

    private void UpdateStatusPill()
    {
        StatusLabel.Text = ViewModel.StatusText;
        StatusDot.Fill = ViewModel.State switch
        {
            TunnelState.Connected => ConnectedBrush,
            TunnelState.Connecting or TunnelState.Disconnecting => BusyBrush,
            TunnelState.Faulted => FaultBrush,
            _ => IdleBrush
        };
    }

    private void OnStateChanged()
    {
        UpdateStatusPill();
        _tray?.SetState(ViewModel.State);

        // Only tell the user about a state change they cannot already see.
        if (!AppWindow.IsVisible && ViewModel.State != _lastNotifiedState)
        {
            switch (ViewModel.State)
            {
                case TunnelState.Connected:
                    _tray?.ShowBalloon("NextVPN", ViewModel.StatusSubtitle);
                    break;
                case TunnelState.Faulted:
                    _tray?.ShowBalloon("NextVPN", "The tunnel stopped unexpectedly.");
                    break;
            }
        }

        _lastNotifiedState = ViewModel.State;
    }

    // -------------------------------------------------------------- tray + window

    private void OnTrayCommand(object? sender, TrayCommand command)
    {
        switch (command)
        {
            case TrayCommand.Show:
                ShowFromTray();
                break;

            case TrayCommand.Toggle:
                ViewModel.ToggleCommand.Execute(null);
                break;

            case TrayCommand.Exit:
                _reallyClosing = true;
                Close();
                break;
        }
    }

    public void ShowFromTray()
    {
        AppWindow.Show();
        if (AppWindow.Presenter is OverlappedPresenter { State: OverlappedPresenterState.Minimized } p)
            p.Restore();

        var hwnd = Win32Interop.GetWindowFromWindowId(AppWindow.Id);
        SetForegroundWindow(hwnd);
    }

    private void OnAppWindowChanged(AppWindow sender, AppWindowChangedEventArgs args)
    {
        if (App.Settings.MinimiseToTray &&
            _tray is { IsAvailable: true } &&
            sender.Presenter is OverlappedPresenter { State: OverlappedPresenterState.Minimized })
        {
            sender.Hide();
        }

        if (args.DidSizeChange || args.DidPositionChange) _geometryDebounce.Start();
    }

    private void OnAppWindowClosing(AppWindow sender, AppWindowClosingEventArgs args)
    {
        // The close button parks the app in the tray rather than tearing the tunnel
        // down, unless the user chose otherwise or asked to quit from the tray menu.
        if (_reallyClosing || !App.Settings.MinimiseToTray || _tray is not { IsAvailable: true })
            return;

        args.Cancel = true;
        sender.Hide();
    }

    private void OnClosed(object sender, WindowEventArgs args)
    {
        _geometryDebounce.Stop();
        SaveGeometry();
        _tray?.Dispose();
        App.SafeShutdown();
    }

    // --------------------------------------------------------------- geometry

    private void RestoreGeometry()
    {
        var s = App.Settings;

        if (s.WindowWidth >= 560 && s.WindowHeight >= 520)
            AppWindow.Resize(new SizeInt32(s.WindowWidth, s.WindowHeight));
        else
            // Chosen so the connection page fits exactly on first run: hero, totals,
            // throughput and detail with nothing below the fold.
            AppWindow.Resize(new SizeInt32(1120, 780));

        if (s.WindowLeft > int.MinValue && s.WindowTop > int.MinValue && IsOnScreen(s.WindowLeft, s.WindowTop))
            AppWindow.Move(new PointInt32(s.WindowLeft, s.WindowTop));
    }

    private void SaveGeometry()
    {
        if (AppWindow.Presenter is OverlappedPresenter { State: not OverlappedPresenterState.Restored }) return;
        if (!AppWindow.IsVisible) return;

        var s = App.Settings;
        s.WindowWidth = AppWindow.Size.Width;
        s.WindowHeight = AppWindow.Size.Height;
        s.WindowLeft = AppWindow.Position.X;
        s.WindowTop = AppWindow.Position.Y;
        s.Save();
    }

    /// <summary>Guards against restoring onto a monitor that is no longer attached.</summary>
    private static bool IsOnScreen(int left, int top)
    {
        var area = DisplayArea.GetFromPoint(new PointInt32(left, top), DisplayAreaFallback.None);
        return area is not null;
    }

    // ------------------------------------------------------------- navigation

    private void OnNavSelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (args.SelectedItem is not NavigationViewItem item) return;

        var page = (item.Tag as string) switch
        {
            "regions" => typeof(RegionsPage),
            "settings" => typeof(SettingsPage),
            "log" => typeof(LogPage),
            _ => typeof(HomePage)
        };

        if (ContentFrame.CurrentSourcePageType != page)
            ContentFrame.Navigate(page, null, new DrillInNavigationTransitionInfo());
    }

    /// <summary>Used by the home page to jump to the region picker.</summary>
    public void NavigateToRegions()
    {
        foreach (var obj in Nav.MenuItems)
        {
            if (obj is NavigationViewItem { Tag: "regions" } item)
            {
                Nav.SelectedItem = item;
                return;
            }
        }
    }

    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hWnd);
}
