using System.ComponentModel;
using System.Diagnostics;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Navigation;
using Microsoft.UI.Xaml.Shapes;
using NextVpn.ViewModels;
using Windows.Foundation;
using Windows.UI;

namespace NextVpn.Views;

public sealed partial class HomePage : Page
{
    public MainViewModel ViewModel { get; } = App.ViewModel!;

    private ConnectAnimator? _animator;

    // The graph shapes are created once and only their geometry is replaced, so a
    // running tunnel does not churn the visual tree once a second.
    private Polygon? _area;
    private Polyline? _downLine;
    private Polyline? _upLine;
    private SolidColorBrush? _downBrush;
    private SolidColorBrush? _upBrush;
    private LinearGradientBrush? _areaBrush;
    private ElementTheme _brushTheme = ElementTheme.Default;

    public HomePage()
    {
        InitializeComponent();

        // Keep the page alive across navigation instead of rebuilding it each time.
        NavigationCacheMode = NavigationCacheMode.Required;

        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
    }

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        _animator = new ConnectAnimator(Ripple1, Ripple2, Arc, Glow, PowerButton);
        _animator.SetState(ViewModel.State);

        ViewModel.PropertyChanged += OnViewModelPropertyChanged;
        ViewModel.RatesChanged += OnRatesChanged;

        DrawGraph();
    }

    /// <summary>
    /// The page is cached, so it is loaded and unloaded repeatedly as the user moves
    /// around. Everything subscribed in OnLoaded is released here, the animator
    /// included: it holds the element handlers, and keeping a stopped one would
    /// accumulate a subscription per visit.
    /// </summary>
    private void OnUnloaded(object sender, RoutedEventArgs e)
    {
        ViewModel.PropertyChanged -= OnViewModelPropertyChanged;
        ViewModel.RatesChanged -= OnRatesChanged;

        _animator?.Dispose();
        _animator = null;
    }

    private void OnViewModelPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(MainViewModel.State))
            _animator?.SetState(ViewModel.State);
    }

    private void OnRatesChanged(object? sender, EventArgs e) => DrawGraph();

    private void OnGraphResized(object sender, SizeChangedEventArgs e) => DrawGraph();

    // ------------------------------------------------------------- responsive

    /// <summary>Below this content width the two-up row becomes a stack.</summary>
    private const double StackBreakpoint = 880;

    private bool? _stacked;

    /// <summary>
    /// Driven from the actual layout width rather than an AdaptiveTrigger.
    /// AdaptiveTrigger measures the window, which includes the navigation pane, so it
    /// switched at the wrong content width.
    /// </summary>
    private void OnRootSizeChanged(object sender, SizeChangedEventArgs e)
    {
        var stacked = e.NewSize.Width < StackBreakpoint;
        if (_stacked == stacked) return;
        _stacked = stacked;

        if (stacked)
        {
            // Both cards span the full three columns, one under the other. The
            // throughput card takes the star row so it still absorbs spare height.
            Grid.SetColumnSpan(ExitCard, 3);
            Grid.SetRow(GraphCard, 3);
            Grid.SetColumn(GraphCard, 0);
            Grid.SetColumnSpan(GraphCard, 3);

            MainRow.Height = GridLength.Auto;
            StackedRow.Height = new GridLength(1, GridUnitType.Star);

            StatusHeading.Style = (Style)Application.Current.Resources["SubtitleTextBlockStyle"];
        }
        else
        {
            Grid.SetColumnSpan(ExitCard, 1);
            Grid.SetRow(GraphCard, 2);
            Grid.SetColumn(GraphCard, 1);
            Grid.SetColumnSpan(GraphCard, 2);

            MainRow.Height = new GridLength(1, GridUnitType.Star);
            StackedRow.Height = new GridLength(0);

            StatusHeading.Style = (Style)Application.Current.Resources["TitleTextBlockStyle"];
        }
    }

    /// <summary>
    /// Makes the layout at least as tall as the viewport, so the star row has spare
    /// height to absorb and the page does not leave a band of dead space under the
    /// last card.
    ///
    /// Deliberately not a binding to ViewportHeight: that made the content height
    /// depend on the viewport while the viewport depended on the content, and the
    /// layout engine re-measured forever. The scroller is sized by its parent, so
    /// reading it here and writing the child breaks the cycle.
    /// </summary>
    private void OnViewportChanged(object sender, SizeChangedEventArgs e)
    {
        var height = e.NewSize.Height;
        if (height <= 0 || Math.Abs(RootLayout.MinHeight - height) < 0.5) return;

        RootLayout.MinHeight = height;
    }

    // -------------------------------------------------------------- throughput

    /// <summary>
    /// Renders recent throughput as a filled download area with an upload line over
    /// it. Both series share one scale, so their relative size stays honest; the
    /// scale is the peak of the visible window.
    /// </summary>
    private void DrawGraph()
    {
        if (GraphCanvas is null) return;

        var w = GraphCanvas.ActualWidth;
        var h = GraphCanvas.ActualHeight;
        var samples = ViewModel.RateHistory;

        if (w < 8 || h < 8 || samples.Count < 2)
        {
            SetGraphVisible(false);
            return;
        }

        EnsureShapes();
        SetGraphVisible(true);

        var peak = 0.0;
        for (var i = 0; i < samples.Count; i++)
            peak = Math.Max(peak, Math.Max(samples[i].Down, samples[i].Up));

        // Headroom so the peak never touches the top edge.
        peak = peak <= 0 ? 1 : peak * 1.15;

        var stepX = w / (samples.Count - 1);

        var down = new PointCollection();
        var up = new PointCollection();
        var area = new PointCollection();

        for (var i = 0; i < samples.Count; i++)
        {
            var x = i * stepX;
            var dy = h - (samples[i].Down / peak * h);
            down.Add(new Point(x, dy));
            area.Add(new Point(x, dy));
            up.Add(new Point(x, h - (samples[i].Up / peak * h)));
        }

        area.Add(new Point(w, h));
        area.Add(new Point(0, h));

        _area!.Points = area;
        _downLine!.Points = down;
        _upLine!.Points = up;
    }

    private void SetGraphVisible(bool visible)
    {
        if (GraphEmpty is not null)
            GraphEmpty.Visibility = visible ? Visibility.Collapsed : Visibility.Visible;

        if (_area is null) return;
        var v = visible ? Visibility.Visible : Visibility.Collapsed;
        _area.Visibility = v;
        _downLine!.Visibility = v;
        _upLine!.Visibility = v;
    }

    private void EnsureShapes()
    {
        var theme = ActualTheme;
        if (_area is not null && _brushTheme == theme) return;

        _brushTheme = theme;

        var downColor = ThemeColor("GraphDown", Color.FromArgb(255, 46, 230, 168));
        var upColor = ThemeColor("GraphUp", Color.FromArgb(255, 90, 185, 255));

        _downBrush = new SolidColorBrush(downColor);
        _upBrush = new SolidColorBrush(upColor);
        _areaBrush = new LinearGradientBrush
        {
            StartPoint = new Point(0, 0),
            EndPoint = new Point(0, 1),
            GradientStops =
            {
                new GradientStop { Color = WithAlpha(downColor, 96), Offset = 0 },
                new GradientStop { Color = WithAlpha(downColor, 8), Offset = 1 }
            }
        };

        if (_area is null)
        {
            _area = new Polygon();
            _downLine = new Polyline
            {
                StrokeThickness = 1.5,
                StrokeLineJoin = PenLineJoin.Round,
                StrokeStartLineCap = PenLineCap.Round,
                StrokeEndLineCap = PenLineCap.Round
            };
            _upLine = new Polyline
            {
                StrokeThickness = 1.5,
                StrokeLineJoin = PenLineJoin.Round,
                StrokeStartLineCap = PenLineCap.Round,
                StrokeEndLineCap = PenLineCap.Round,
                Opacity = 0.9
            };

            GraphCanvas.Children.Add(_area);
            GraphCanvas.Children.Add(_upLine);
            GraphCanvas.Children.Add(_downLine);
        }

        _area.Fill = _areaBrush;
        _downLine!.Stroke = _downBrush;
        _upLine!.Stroke = _upBrush;
    }

    private static Color WithAlpha(Color c, byte alpha) => Color.FromArgb(alpha, c.R, c.G, c.B);

    private Color ThemeColor(string key, Color fallback) =>
        Application.Current.Resources.TryGetValue(key, out var v) && v is Color c ? c : fallback;

    // ----------------------------------------------------------------- commands

    private void OnPickRegion(object sender, RoutedEventArgs e) => App.Window?.NavigateToRegions();

    private void OnOpenSponsorPage(object sender, RoutedEventArgs e)
    {
        var url = ViewModel.SponsorPageUrl;
        if (string.IsNullOrEmpty(url)) return;

        try
        {
            Process.Start(new ProcessStartInfo { FileName = url, UseShellExecute = true });
        }
        catch (Exception ex) when (ex is System.ComponentModel.Win32Exception or IOException)
        {
        }
    }
}
