using System.Collections.Specialized;
using System.Text;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using NextVpn.ViewModels;
using Windows.ApplicationModel.DataTransfer;

namespace NextVpn.Views;

public sealed partial class LogPage : Page
{
    public MainViewModel ViewModel { get; } = App.ViewModel!;

    private bool _autoScroll = true;

    public LogPage()
    {
        InitializeComponent();
        NavigationCacheMode = Microsoft.UI.Xaml.Navigation.NavigationCacheMode.Required;

        Loaded += (_, _) =>
        {
            ViewModel.Log.CollectionChanged += OnLogChanged;
            UpdateEmptyNote();
            ScrollToEnd();
        };
        Unloaded += (_, _) => ViewModel.Log.CollectionChanged -= OnLogChanged;
    }

    private void OnLogChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        UpdateEmptyNote();

        if (e.Action == NotifyCollectionChangedAction.Add && _autoScroll)
            DispatcherQueue.TryEnqueue(ScrollToEnd);
    }

    private void UpdateEmptyNote() =>
        EmptyNote.Visibility = ViewModel.Log.Count == 0 ? Visibility.Visible : Visibility.Collapsed;

    private void ScrollToEnd()
    {
        if (ViewModel.Log.Count > 0)
            LogList.ScrollIntoView(ViewModel.Log[^1]);
    }

    private void OnCopy(object sender, RoutedEventArgs e)
    {
        var sb = new StringBuilder();
        foreach (var entry in ViewModel.Log)
            sb.Append(entry.TimeText).Append("  ").Append(entry.Type).Append("  ").AppendLine(entry.Message);

        var package = new DataPackage();
        package.SetText(sb.ToString());
        Clipboard.SetContent(package);
    }
}
