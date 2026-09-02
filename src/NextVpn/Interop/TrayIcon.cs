using System.Runtime.InteropServices;
using NextVpn.Core;

namespace NextVpn.Interop;

public enum TrayCommand { Show, Toggle, Exit }

/// <summary>
/// Notification-area icon built directly on Shell_NotifyIcon.
///
/// It owns a message-only window created on the UI thread, so its messages are
/// pumped by the application's existing message loop and every event is raised
/// back on the UI thread. No third-party dependency, and nothing to keep in sync
/// with the XAML framework's own windowing.
/// </summary>
public sealed class TrayIcon : IDisposable
{
    private const int WM_APP = 0x8000;
    private const int CallbackMessage = WM_APP + 1;

    private const int WM_LBUTTONUP = 0x0202;
    private const int WM_LBUTTONDBLCLK = 0x0203;
    private const int WM_RBUTTONUP = 0x0205;
    private const int WM_DESTROY = 0x0002;

    private const int NIM_ADD = 0, NIM_MODIFY = 1, NIM_DELETE = 2;
    private const int NIF_MESSAGE = 0x01, NIF_ICON = 0x02, NIF_TIP = 0x04, NIF_INFO = 0x10;

    private const int IMAGE_ICON = 1;
    private const int LR_LOADFROMFILE = 0x0010;
    private const int LR_DEFAULTSIZE = 0x0040;

    private const uint TPM_RIGHTBUTTON = 0x0002;
    private const uint TPM_RETURNCMD = 0x0100;

    private const uint MF_STRING = 0x0000, MF_SEPARATOR = 0x0800;

    private const int IdToggle = 1, IdShow = 2, IdExit = 3;

    private readonly WndProc _wndProc;   // held so the delegate is not collected
    private IntPtr _hwnd;
    private IntPtr _icon;
    private readonly string _className = "NextVpnTray_" + Guid.NewGuid().ToString("N");
    private bool _added;
    private TunnelState _state = TunnelState.Disconnected;

    public event EventHandler<TrayCommand>? Command;

    public TrayIcon()
    {
        _wndProc = OnMessage;

        var wc = new WNDCLASSEX
        {
            cbSize = Marshal.SizeOf<WNDCLASSEX>(),
            lpfnWndProc = Marshal.GetFunctionPointerForDelegate(_wndProc),
            hInstance = GetModuleHandle(null),
            lpszClassName = _className
        };

        if (RegisterClassEx(ref wc) == 0) return;

        // HWND_MESSAGE (-3): a window that exists only to receive messages.
        _hwnd = CreateWindowEx(0, _className, "NextVPN", 0, 0, 0, 0, 0, new IntPtr(-3), IntPtr.Zero, wc.hInstance, IntPtr.Zero);
        if (_hwnd == IntPtr.Zero) return;

        SetState(TunnelState.Disconnected);
    }

    public bool IsAvailable => _hwnd != IntPtr.Zero;

    /// <summary>Swaps the icon and hover text to match the tunnel state.</summary>
    public void SetState(TunnelState state)
    {
        if (_hwnd == IntPtr.Zero) return;
        _state = state;

        var file = state switch
        {
            TunnelState.Connected => "tray-on.ico",
            TunnelState.Connecting or TunnelState.Disconnecting => "tray-connecting.ico",
            _ => "tray-off.ico"
        };

        var tip = state switch
        {
            TunnelState.Connected => "NextVPN — connected",
            TunnelState.Connecting => "NextVPN — connecting",
            TunnelState.Disconnecting => "NextVPN — disconnecting",
            TunnelState.Faulted => "NextVPN — connection failed",
            _ => "NextVPN — not connected"
        };

        var previous = _icon;
        _icon = LoadIconFile(file);

        var data = NewData();
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP;
        data.uCallbackMessage = CallbackMessage;
        data.hIcon = _icon;
        data.szTip = tip;

        Shell_NotifyIcon(_added ? NIM_MODIFY : NIM_ADD, ref data);
        _added = true;

        if (previous != IntPtr.Zero && previous != _icon) DestroyIcon(previous);
    }

    public void ShowBalloon(string title, string message)
    {
        if (_hwnd == IntPtr.Zero || !_added) return;

        var data = NewData();
        data.uFlags = NIF_INFO;
        data.szInfoTitle = title;
        data.szInfo = message;
        data.dwInfoFlags = 0;
        Shell_NotifyIcon(NIM_MODIFY, ref data);
    }

    // ---------------------------------------------------------------- messages

    private IntPtr OnMessage(IntPtr hwnd, uint msg, IntPtr wParam, IntPtr lParam)
    {
        if (msg == CallbackMessage)
        {
            switch ((int)lParam)
            {
                case WM_LBUTTONUP:
                case WM_LBUTTONDBLCLK:
                    Command?.Invoke(this, TrayCommand.Show);
                    return IntPtr.Zero;

                case WM_RBUTTONUP:
                    ShowMenu();
                    return IntPtr.Zero;
            }
        }
        else if (msg == WM_DESTROY)
        {
            Remove();
        }

        return DefWindowProc(hwnd, msg, wParam, lParam);
    }

    private void ShowMenu()
    {
        var menu = CreatePopupMenu();
        if (menu == IntPtr.Zero) return;

        try
        {
            var toggle = _state switch
            {
                TunnelState.Connected => "Disconnect",
                TunnelState.Connecting or TunnelState.Disconnecting => "Cancel",
                _ => "Connect"
            };

            AppendMenu(menu, MF_STRING, IdToggle, toggle);
            AppendMenu(menu, MF_SEPARATOR, 0, null);
            AppendMenu(menu, MF_STRING, IdShow, "Open NextVPN");
            AppendMenu(menu, MF_SEPARATOR, 0, null);
            AppendMenu(menu, MF_STRING, IdExit, "Quit");

            GetCursorPos(out var pt);

            // Required so the menu closes when the user clicks elsewhere.
            SetForegroundWindow(_hwnd);

            var chosen = TrackPopupMenuEx(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD, pt.X, pt.Y, _hwnd, IntPtr.Zero);

            // Classic Win32 workaround: without this the next menu can fail to appear.
            PostMessage(_hwnd, 0, IntPtr.Zero, IntPtr.Zero);

            switch (chosen)
            {
                case IdToggle: Command?.Invoke(this, TrayCommand.Toggle); break;
                case IdShow: Command?.Invoke(this, TrayCommand.Show); break;
                case IdExit: Command?.Invoke(this, TrayCommand.Exit); break;
            }
        }
        finally
        {
            DestroyMenu(menu);
        }
    }

    private NOTIFYICONDATA NewData() => new()
    {
        cbSize = Marshal.SizeOf<NOTIFYICONDATA>(),
        hWnd = _hwnd,
        uID = 1,
        szTip = "",
        szInfo = "",
        szInfoTitle = ""
    };

    private static IntPtr LoadIconFile(string fileName)
    {
        var path = Path.Combine(Paths.AppDirectory, "Assets", fileName);
        return File.Exists(path)
            ? LoadImage(IntPtr.Zero, path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
            : IntPtr.Zero;
    }

    private void Remove()
    {
        if (!_added) return;
        var data = NewData();
        Shell_NotifyIcon(NIM_DELETE, ref data);
        _added = false;
    }

    public void Dispose()
    {
        Remove();

        if (_icon != IntPtr.Zero) { DestroyIcon(_icon); _icon = IntPtr.Zero; }
        if (_hwnd != IntPtr.Zero) { DestroyWindow(_hwnd); _hwnd = IntPtr.Zero; }

        UnregisterClass(_className, GetModuleHandle(null));
    }

    // ---------------------------------------------------------------- interop

    private delegate IntPtr WndProc(IntPtr hwnd, uint msg, IntPtr wParam, IntPtr lParam);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct WNDCLASSEX
    {
        public int cbSize;
        public int style;
        public IntPtr lpfnWndProc;
        public int cbClsExtra;
        public int cbWndExtra;
        public IntPtr hInstance;
        public IntPtr hIcon;
        public IntPtr hCursor;
        public IntPtr hbrBackground;
        [MarshalAs(UnmanagedType.LPWStr)] public string? lpszMenuName;
        [MarshalAs(UnmanagedType.LPWStr)] public string lpszClassName;
        public IntPtr hIconSm;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct NOTIFYICONDATA
    {
        public int cbSize;
        public IntPtr hWnd;
        public int uID;
        public int uFlags;
        public int uCallbackMessage;
        public IntPtr hIcon;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string szTip;
        public int dwState;
        public int dwStateMask;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] public string szInfo;
        public int uVersion;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 64)] public string szInfoTitle;
        public int dwInfoFlags;
        public Guid guidItem;
        public IntPtr hBalloonIcon;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct POINT { public int X; public int Y; }

    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    private static extern bool Shell_NotifyIcon(int dwMessage, ref NOTIFYICONDATA lpData);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern ushort RegisterClassEx(ref WNDCLASSEX lpwcx);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool UnregisterClass(string lpClassName, IntPtr hInstance);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateWindowEx(int exStyle, string className, string windowName,
        int style, int x, int y, int width, int height, IntPtr parent, IntPtr menu, IntPtr instance, IntPtr param);

    [DllImport("user32.dll")]
    private static extern bool DestroyWindow(IntPtr hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr DefWindowProc(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr GetModuleHandle(string? lpModuleName);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr LoadImage(IntPtr hinst, string lpszName, uint uType, int cx, int cy, uint fuLoad);

    [DllImport("user32.dll")]
    private static extern bool DestroyIcon(IntPtr hIcon);

    [DllImport("user32.dll")]
    private static extern IntPtr CreatePopupMenu();

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern bool AppendMenu(IntPtr hMenu, uint uFlags, int uIDNewItem, string? lpNewItem);

    [DllImport("user32.dll")]
    private static extern bool DestroyMenu(IntPtr hMenu);

    [DllImport("user32.dll")]
    private static extern int TrackPopupMenuEx(IntPtr hMenu, uint fuFlags, int x, int y, IntPtr hwnd, IntPtr lptpm);

    [DllImport("user32.dll")]
    private static extern bool GetCursorPos(out POINT lpPoint);

    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern bool PostMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
}
