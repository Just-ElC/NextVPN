using System.Collections.ObjectModel;
using System.Collections.Specialized;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using NextVpn.Core;
using NextVpn.ViewModels;

namespace NextVpn.Views;

public sealed partial class RegionsPage : Page
{
    public MainViewModel ViewModel { get; } = App.ViewModel!;

    public ObservableCollection<RegionInfo> Filtered { get; } = new();

    private bool _suppressSelection;

    public RegionsPage()
    {
        InitializeComponent();
        NavigationCacheMode = NavigationCacheMode.Required;

        ApplyFilter("");

        // Subscribed per view lifetime, not in the constructor: with page caching a
        // constructor subscription would outlive every navigation away from here.
        Loaded += (_, _) =>
        {
            ViewModel.AvailableRegions.CollectionChanged += OnRegionsChanged;
            ApplyFilter(SearchBox.Text);
            SelectCurrent();
        };
        Unloaded += (_, _) => ViewModel.AvailableRegions.CollectionChanged -= OnRegionsChanged;
    }

    private void OnRegionsChanged(object? sender, NotifyCollectionChangedEventArgs e) =>
        ApplyFilter(SearchBox.Text);

    private void ApplyFilter(string query)
    {
        query = (query ?? "").Trim();

        Filtered.Clear();
        foreach (var r in ViewModel.AvailableRegions)
        {
            if (query.Length == 0 ||
                r.Name.Contains(query, StringComparison.CurrentCultureIgnoreCase) ||
                r.Code.Contains(query, StringComparison.OrdinalIgnoreCase))
            {
                Filtered.Add(r);
            }
        }

        UpdateEmptyNote(query);
        SelectCurrent();
    }

    /// <summary>
    /// Explains an empty or nearly empty list. Before the first connection the engine
    /// has not reported which countries exist, so the list holds only the pseudo-region
    /// and would otherwise look broken.
    /// </summary>
    private void UpdateEmptyNote(string query)
    {
        var searching = query.Length > 0;
        var countries = Filtered.Count(r => r.IsCountry);

        if (countries > 0)
        {
            EmptyNote.Visibility = Visibility.Collapsed;
            return;
        }

        EmptyNoteText.Text = searching
            ? $"No location matches “{query}”."
            : "Countries appear here once the tunnel has reached the network. Until then, "
              + "Best performance lets the engine choose.";
        EmptyNote.Visibility = Visibility.Visible;
    }

    private void SelectCurrent()
    {
        _suppressSelection = true;
        RegionList.SelectedItem = Filtered.FirstOrDefault(r => r.Code == ViewModel.SelectedRegion.Code);
        _suppressSelection = false;
    }

    private void OnSearchChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args)
    {
        if (args.Reason == AutoSuggestionBoxTextChangeReason.UserInput)
            ApplyFilter(sender.Text);
    }

    private void OnRegionSelected(object sender, SelectionChangedEventArgs e)
    {
        if (_suppressSelection) return;
        if (RegionList.SelectedItem is RegionInfo region)
            ViewModel.SelectedRegion = region;
    }
}
