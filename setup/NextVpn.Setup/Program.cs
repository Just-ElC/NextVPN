using System.Diagnostics;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using Microsoft.Win32;

namespace NextVpn.Setup;

/// <summary>
/// NextVPN setup and uninstaller.
///
/// Everything it does is per-user and reversible, and this file is the whole list:
///
///   %LOCALAPPDATA%\Programs\NextVPN                     the application
///   Start Menu\Programs\NextVPN.lnk                     the shortcut
///   HKCU\...\CurrentVersion\Uninstall\NextVPN           the Installed apps entry
///
/// No administrator rights, no service, no scheduled task, no driver, and nothing
/// written outside those three places. Settings live in %LOCALAPPDATA%\NextVPN and
/// are deliberately left alone by the uninstaller unless --purge is passed.
/// </summary>
internal static class Program
{
    private const string AppName = "NextVPN";
    private const string ExeName = "NextVPN.exe";
    private const string UninstallerName = "NextVPN-Uninstall.exe";
    private const string PayloadResource = "NextVpn.Setup.payload.zip";
    private const string RegistryKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\NextVPN";
    private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string RuntimeDownload = "https://dotnet.microsoft.com/download/dotnet/8.0/runtime";

    private static bool _silent;

    private static int Main(string[] args)
    {
        try
        {
            var options = Options.Parse(args);
            _silent = options.Silent;

            if (options.Help)
            {
                Say(Usage(), "NextVPN setup", Info);
                return 0;
            }

            return options.Uninstall ? Uninstall(options) : Install(options);
        }
        catch (Exception ex)
        {
            Say($"Setup could not finish:\n\n{ex.Message}", "NextVPN setup", Error);
            return 1;
        }
    }

    // ---------------------------------------------------------------- install

    private static int Install(Options options)
    {
        var payload = Assembly.GetExecutingAssembly().GetManifestResourceStream(PayloadResource);
        if (payload is null)
        {
            Say("This build carries no application payload. It can only uninstall.\n\n" +
                "Run it with --uninstall, or download the setup from the release page.",
                "NextVPN setup", Error);
            return 1;
        }

        var target = options.Directory ?? DefaultInstallDirectory;
        var exePath = Path.Combine(target, ExeName);

        if (IsRunning(out var where))
        {
            Say($"NextVPN is running{(where is null ? "" : $" from {where}")}.\n\n" +
                "Quit it from the notification area and run this again.", "NextVPN setup", Error);
            return 2;
        }

        if (!HasDesktopRuntime())
        {
            var open = Ask(
                "NextVPN needs the .NET 8 Desktop Runtime (x64), which is not installed.\n\n" +
                "Open the download page now? Install it, then run this setup again.",
                "NextVPN setup");

            if (open) Open(RuntimeDownload);
            return 2;
        }

        if (!options.Silent && !Ask(
                $"Install {AppName} for your account only?\n\n" +
                $"Application:  {target}\n" +
                $"Settings:     {DataDirectory}\n\n" +
                "No administrator rights are needed and nothing else on the machine is touched.",
                "NextVPN setup"))
        {
            return 2;
        }

        // A previous version is removed rather than written over, so a file that was
        // dropped upstream does not survive as a stale copy next to the new build.
        if (Directory.Exists(target) && File.Exists(exePath)) ClearDirectory(target);
        Directory.CreateDirectory(target);

        using (payload)
        using (var archive = new ZipArchive(payload, ZipArchiveMode.Read))
            Extract(archive, target);

        if (!File.Exists(exePath))
        {
            Say("The payload did not contain NextVPN.exe. Nothing was installed.", "NextVPN setup", Error);
            return 1;
        }

        if (!options.NoShortcut) CreateShortcut(StartMenuShortcut, exePath, target);

        RegisterInstalledApp(target, exePath);

        if (options.Silent) return 0;

        if (Ask($"{AppName} is installed.\n\nStart it now?", "NextVPN setup"))
            Open(exePath, target);

        return 0;
    }

    private static void Extract(ZipArchive archive, string target)
    {
        var root = Path.GetFullPath(target);

        foreach (var entry in archive.Entries)
        {
            // Directory entries have an empty name; everything else must resolve
            // inside the install directory, whatever the archive claims.
            var destination = Path.GetFullPath(Path.Combine(root, entry.FullName));
            if (!destination.StartsWith(root, StringComparison.OrdinalIgnoreCase))
                throw new IOException($"Refusing to write outside the install directory: {entry.FullName}");

            if (entry.Name.Length == 0)
            {
                Directory.CreateDirectory(destination);
                continue;
            }

            Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
            entry.ExtractToFile(destination, overwrite: true);
        }
    }

    private static void RegisterInstalledApp(string target, string exePath)
    {
        // HKCU only: this is what makes the app appear in Settings > Installed apps
        // with a working Uninstall button, for this user and no one else.
        using var key = Registry.CurrentUser.CreateSubKey(RegistryKey);
        if (key is null) return;

        var uninstaller = Path.Combine(target, UninstallerName);
        var version = Assembly.GetExecutingAssembly().GetName().Version?.ToString(3) ?? "1.0.0";

        key.SetValue("DisplayName", AppName);
        key.SetValue("DisplayVersion", version);
        key.SetValue("Publisher", "NextOS");
        key.SetValue("DisplayIcon", exePath);
        key.SetValue("InstallLocation", target);
        key.SetValue("UninstallString", $"\"{uninstaller}\" --uninstall");
        key.SetValue("QuietUninstallString", $"\"{uninstaller}\" --uninstall --silent");
        key.SetValue("NoModify", 1, RegistryValueKind.DWord);
        key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
        key.SetValue("EstimatedSize", (int)(DirectorySize(target) / 1024), RegistryValueKind.DWord);
        key.SetValue("InstallDate", DateTime.Now.ToString("yyyyMMdd"));
    }

    // -------------------------------------------------------------- uninstall

    private static int Uninstall(Options options)
    {
        var target = options.Directory ?? InstalledDirectory ?? DefaultInstallDirectory;

        if (IsRunning(out _))
        {
            Say("NextVPN is running. Quit it from the notification area first.", "NextVPN uninstall", Error);
            return 2;
        }

        // A leftover proxy backup means a previous run was killed while connected and
        // Windows may still be pointed at a local port that no longer exists. Starting
        // NextVPN once puts the original settings back; removing the app first would
        // leave the machine without working network.
        var backup = Path.Combine(DataDirectory, "proxy-backup.json");
        if (!options.Silent && File.Exists(backup))
        {
            var exePath = Path.Combine(target, ExeName);
            var repair = File.Exists(exePath) && Ask(
                "NextVPN still holds a saved copy of your previous proxy settings, which means " +
                "Windows may currently be pointed at its local proxy.\n\n" +
                "Start NextVPN once so it can put your settings back? Uninstall again afterwards.",
                "NextVPN uninstall");

            if (repair)
            {
                Open(exePath, target);
                return 2;
            }
        }

        if (!options.Silent && !Ask(
                $"Remove {AppName}?\n\n" +
                $"{target}\n\n" +
                (options.Purge
                    ? $"Your settings in {DataDirectory} will be deleted as well."
                    : $"Your settings in {DataDirectory} will be left in place."),
                "NextVPN uninstall"))
        {
            return 2;
        }

        RemoveRunEntry(target);
        RemoveShortcut(target);

        // Only retire the Installed apps entry if it is the one describing this
        // directory. Removing a copy from somewhere else must not unregister the
        // installation the user still has.
        var registered = InstalledDirectory;
        if (registered is null || PathsMatch(registered, target))
        {
            try { Registry.CurrentUser.DeleteSubKeyTree(RegistryKey, throwOnMissingSubKey: false); }
            catch (Exception ex) when (ex is UnauthorizedAccessException or System.Security.SecurityException) { }
        }

        if (options.Purge) TryDeleteDirectory(DataDirectory);

        // The uninstaller is running from inside the directory it has to remove, so
        // the last step is handed to a detached shell that waits for this process.
        ScheduleSelfRemoval(target);

        if (!options.Silent) Say($"{AppName} has been removed.", "NextVPN uninstall", Info);
        return 0;
    }

    private static void RemoveRunEntry(string target)
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(RunKey, writable: true);
            if (key?.GetValue(AppName) is not string value) return;

            // Only ours: another copy of NextVPN elsewhere keeps its own entry.
            if (value.Contains(target, StringComparison.OrdinalIgnoreCase))
                key.DeleteValue(AppName, throwOnMissingValue: false);
        }
        catch (Exception ex) when (ex is UnauthorizedAccessException or System.Security.SecurityException or IOException)
        {
        }
    }

    private static void RemoveShortcut(string target)
    {
        // Only ever remove a shortcut that points at this installation: the same file
        // name may since have been repointed at a copy somewhere else.
        if (PointsInto(StartMenuShortcut, target)) TryDelete(StartMenuShortcut);
    }

    /// <summary>
    /// Whether a shortcut refers to a path inside the given directory.
    ///
    /// Read from the file rather than through the shell, so the uninstaller does not
    /// depend on COM being reachable at the moment it runs. A shell link stores its
    /// target as text; finding the directory in either encoding is enough to tell
    /// ours apart from someone else's.
    /// </summary>
    private static bool PointsInto(string shortcut, string directory)
    {
        try
        {
            if (!File.Exists(shortcut)) return false;

            var bytes = File.ReadAllBytes(shortcut);
            return Contains(bytes, System.Text.Encoding.Unicode.GetBytes(directory))
                || Contains(bytes, System.Text.Encoding.ASCII.GetBytes(directory));
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return false;
        }

        static bool Contains(byte[] haystack, byte[] needle)
        {
            if (needle.Length == 0 || haystack.Length < needle.Length) return false;

            for (var i = 0; i <= haystack.Length - needle.Length; i++)
            {
                var found = true;
                for (var j = 0; j < needle.Length; j++)
                {
                    // Paths are case-insensitive on Windows, and the two encodings
                    // differ only in the zero bytes, which compare equal either way.
                    if (Fold(haystack[i + j]) == Fold(needle[j])) continue;
                    found = false;
                    break;
                }
                if (found) return true;
            }
            return false;
        }

        static byte Fold(byte b) => b is >= (byte)'A' and <= (byte)'Z' ? (byte)(b + 32) : b;
    }

    private static void ScheduleSelfRemoval(string target)
    {
        foreach (var file in SafeEnumerateFiles(target))
        {
            if (!string.Equals(Path.GetFileName(file), UninstallerName, StringComparison.OrdinalIgnoreCase))
                TryDelete(file);
        }

        var command = $"/c ping 127.0.0.1 -n 3 >nul & rd /s /q \"{target}\"";
        try
        {
            Process.Start(new ProcessStartInfo("cmd.exe", command)
            {
                CreateNoWindow = true,
                UseShellExecute = false,
                WindowStyle = ProcessWindowStyle.Hidden
            });
        }
        catch (Exception ex) when (ex is System.ComponentModel.Win32Exception or IOException)
        {
        }
    }

    // ------------------------------------------------------------------ files

    private static void ClearDirectory(string path)
    {
        foreach (var file in SafeEnumerateFiles(path)) TryDelete(file);

        foreach (var directory in Directory.EnumerateDirectories(path))
            TryDeleteDirectory(directory);
    }

    private static IEnumerable<string> SafeEnumerateFiles(string path)
    {
        try { return Directory.EnumerateFiles(path, "*", SearchOption.AllDirectories).ToList(); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { return []; }
    }

    private static long DirectorySize(string path)
    {
        long total = 0;
        foreach (var file in SafeEnumerateFiles(path))
        {
            try { total += new FileInfo(file).Length; }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { }
        }
        return total;
    }

    private static void TryDelete(string path)
    {
        try { if (File.Exists(path)) File.Delete(path); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { }
    }

    private static void TryDeleteDirectory(string path)
    {
        try { if (Directory.Exists(path)) Directory.Delete(path, recursive: true); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { }
    }

    // ------------------------------------------------------------ environment

    private static string DefaultInstallDirectory => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", AppName);

    private static string DataDirectory => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), AppName);

    private static string StartMenuShortcut => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        @"Microsoft\Windows\Start Menu\Programs", AppName + ".lnk");

    /// <summary>Where a previous run of this installer put the application, if any.</summary>
    private static string? InstalledDirectory
    {
        get
        {
            try
            {
                using var key = Registry.CurrentUser.OpenSubKey(RegistryKey);
                return key?.GetValue("InstallLocation") as string;
            }
            catch (Exception ex) when (ex is UnauthorizedAccessException or System.Security.SecurityException)
            {
                return null;
            }
        }
    }

    private static bool PathsMatch(string a, string b) =>
        string.Equals(
            Path.TrimEndingDirectorySeparator(Path.GetFullPath(a)),
            Path.TrimEndingDirectorySeparator(Path.GetFullPath(b)),
            StringComparison.OrdinalIgnoreCase);

    private static bool IsRunning(out string? path)
    {
        path = null;

        foreach (var process in Process.GetProcessesByName("NextVPN"))
        {
            try { path ??= process.MainModule?.FileName; }
            catch (Exception ex) when (ex is InvalidOperationException
                                          or System.ComponentModel.Win32Exception
                                          or NotSupportedException) { }
            finally { process.Dispose(); }

            return true;
        }
        return false;
    }

    /// <summary>
    /// The application is framework-dependent, so the .NET 8 Desktop Runtime has to be
    /// there. Looked for on disk rather than by running dotnet, which need not exist.
    /// </summary>
    private static bool HasDesktopRuntime()
    {
        foreach (var root in RuntimeRoots())
        {
            var shared = Path.Combine(root, "shared", "Microsoft.WindowsDesktop.App");
            if (!Directory.Exists(shared)) continue;

            foreach (var directory in Directory.EnumerateDirectories(shared))
            {
                var name = Path.GetFileName(directory);
                if (int.TryParse(name.Split('.')[0], out var major) && major >= 8) return true;
            }
        }
        return false;

        static IEnumerable<string> RuntimeRoots()
        {
            var seen = new List<string>();

            foreach (var candidate in new[]
                     {
                         Environment.GetEnvironmentVariable("DOTNET_ROOT"),
                         Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "dotnet"),
                         Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".dotnet"),
                         Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                                      "Microsoft", "dotnet"),
                     })
            {
                if (string.IsNullOrEmpty(candidate) || seen.Contains(candidate)) continue;
                seen.Add(candidate);
                yield return candidate;
            }
        }
    }

    private static void CreateShortcut(string shortcut, string exePath, string workingDirectory)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(shortcut)!);

        // Written through the shell rather than by hand: a shortcut is a binary
        // format, and an existing pinned tile keeps working when the file it already
        // points at is updated in place.
        RunPowerShell(
            $"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{Escape(shortcut)}');" +
            $"$s.TargetPath='{Escape(exePath)}';" +
            $"$s.WorkingDirectory='{Escape(workingDirectory)}';" +
            $"$s.IconLocation='{Escape(exePath)},0';" +
            "$s.Description='NextVPN';" +
            "$s.Save()");
    }

    private static bool RunPowerShell(string script)
    {
        try
        {
            using var process = Process.Start(new ProcessStartInfo("powershell.exe",
                $"-NoProfile -NonInteractive -WindowStyle Hidden -Command \"{script}\"")
            {
                CreateNoWindow = true,
                UseShellExecute = false,
                WindowStyle = ProcessWindowStyle.Hidden
            });

            if (process is null) return false;
            return process.WaitForExit(30_000) && process.ExitCode == 0;
        }
        catch (Exception ex) when (ex is System.ComponentModel.Win32Exception or IOException)
        {
            return false;
        }
    }

    /// <summary>Single quotes are the escape character inside a PowerShell literal string.</summary>
    private static string Escape(string value) => value.Replace("'", "''");

    private static void Open(string path, string? workingDirectory = null)
    {
        try
        {
            Process.Start(new ProcessStartInfo(path)
            {
                UseShellExecute = true,
                WorkingDirectory = workingDirectory ?? ""
            });
        }
        catch (Exception ex) when (ex is System.ComponentModel.Win32Exception or IOException)
        {
        }
    }

    // --------------------------------------------------------------- messages

    private const uint Info = 0x40;      // MB_ICONINFORMATION
    private const uint Error = 0x10;     // MB_ICONERROR
    private const uint YesNo = 0x24;     // MB_YESNO | MB_ICONQUESTION
    private const int Yes = 6;           // IDYES

    private static void Say(string text, string caption, uint icon)
    {
        if (_silent) return;
        MessageBoxW(IntPtr.Zero, text, caption, icon);
    }

    private static bool Ask(string text, string caption) =>
        _silent || MessageBoxW(IntPtr.Zero, text, caption, YesNo) == Yes;

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int MessageBoxW(IntPtr owner, string text, string caption, uint type);

    private static string Usage() =>
        """
        NextVPN setup

          (no arguments)   install for the current user
          --silent         install or uninstall without asking anything
          --dir=<path>     install somewhere other than %LOCALAPPDATA%\Programs\NextVPN
          --no-shortcut    do not create the Start menu shortcut
          --uninstall      remove the application
          --purge          with --uninstall, also delete settings
        """;

    // ---------------------------------------------------------------- options

    private sealed class Options
    {
        public bool Silent { get; private init; }
        public bool Uninstall { get; private init; }
        public bool Purge { get; private init; }
        public bool NoShortcut { get; private init; }
        public bool Help { get; private init; }
        public string? Directory { get; private init; }

        public static Options Parse(string[] args)
        {
            bool silent = false, uninstall = false, purge = false, noShortcut = false, help = false;
            string? directory = null;

            foreach (var raw in args)
            {
                var arg = raw.TrimStart('-', '/');

                if (arg.StartsWith("dir=", StringComparison.OrdinalIgnoreCase))
                {
                    directory = Path.GetFullPath(arg[4..].Trim('"'));
                    continue;
                }

                switch (arg.ToLowerInvariant())
                {
                    case "s":
                    case "silent":
                    case "quiet":
                        silent = true;
                        break;
                    case "uninstall":
                    case "remove":
                        uninstall = true;
                        break;
                    case "purge":
                        purge = true;
                        break;
                    case "no-shortcut":
                        noShortcut = true;
                        break;
                    case "?":
                    case "h":
                    case "help":
                        help = true;
                        break;
                }
            }

            return new Options
            {
                Silent = silent,
                Uninstall = uninstall,
                Purge = purge,
                NoShortcut = noShortcut,
                Help = help,
                Directory = directory
            };
        }
    }
}
