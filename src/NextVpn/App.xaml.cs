using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using NextVpn.Core;
using NextVpn.Interop;
using NextVpn.ViewModels;

namespace NextVpn;

public partial class App : Application
{
    private const string MutexName = @"Local\NextVPN.SingleInstance";
    private const string WakeEventName = @"Local\NextVPN.ShowWindow";

    private static Mutex? _singleInstanceMutex;
    private static EventWaitHandle? _wakeEvent;

    public static AppSettings Settings { get; private set; } = new();
    public static MainViewModel? ViewModel { get; private set; }
    public static MainWindow? Window { get; private set; }

    public App()
    {
        InitializeComponent();

        UnhandledException += (_, _) =>
        {
            // A crash must never leave the machine pointing at a dead local proxy.
            SafeShutdown();
        };

        AppDomain.CurrentDomain.ProcessExit += (_, _) => SafeShutdown();
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        // Only one instance may own the tunnel and the system proxy. A second launch
        // hands focus back to the running one instead of dying silently, which is what
        // a user clicking the shortcut again actually expects.
        _singleInstanceMutex = new Mutex(initiallyOwned: true, MutexName, out var isFirst);
        if (!isFirst)
        {
            SignalExistingInstance();
            Exit();
            return;
        }

        Directory.CreateDirectory(Paths.DataDirectory);

        // If a previous run was killed while connected, put the proxy back first.
        SystemProxy.RecoverIfStale();

        Settings = AppSettings.Load();
        ViewModel = new MainViewModel(Settings);

        Window = new MainWindow();

        if (StartHidden())
            Window.AppWindow.Hide();
        else
            Window.Activate();

        StartWakeListener();

        if (Settings.ConnectOnLaunch)
            ViewModel.ConnectCommand.Execute(null);
    }

    /// <summary>
    /// True when the app should come up parked in the tray: either the user asked for
    /// it, or Windows started us from the sign-in entry, which passes --minimised.
    /// </summary>
    private static bool StartHidden()
    {
        if (!Settings.MinimiseToTray) return false;

        if (Settings.StartMinimised) return true;

        foreach (var arg in Environment.GetCommandLineArgs())
        {
            if (arg.Equals("--minimised", StringComparison.OrdinalIgnoreCase) ||
                arg.Equals("--minimized", StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }
        return false;
    }

    private static void SignalExistingInstance()
    {
        try
        {
            if (EventWaitHandle.TryOpenExisting(WakeEventName, out var handle))
            {
                handle.Set();
                handle.Dispose();
            }
        }
        catch (WaitHandleCannotBeOpenedException)
        {
        }
    }

    /// <summary>Waits for a later launch to ask us to surface the window.</summary>
    private static void StartWakeListener()
    {
        _wakeEvent = new EventWaitHandle(false, EventResetMode.AutoReset, WakeEventName);
        var queue = DispatcherQueue.GetForCurrentThread();

        var thread = new Thread(() =>
        {
            while (_wakeEvent is not null && _wakeEvent.WaitOne())
                queue.TryEnqueue(() => Window?.ShowFromTray());
        })
        {
            IsBackground = true,
            Name = "NextVPN wake listener"
        };
        thread.Start();
    }

    private static bool _shutdownDone;

    public static void SafeShutdown()
    {
        if (_shutdownDone) return;
        _shutdownDone = true;

        try { ViewModel?.Shutdown(); } catch (Exception) { /* shutting down anyway */ }
        try { SystemProxy.Revert(); } catch (Exception) { /* shutting down anyway */ }
    }
}
