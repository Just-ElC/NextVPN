using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Data;
using Microsoft.UI.Xaml.Media;
using NextVpn.Core;
using NextVpn.ViewModels;
using Windows.UI;

namespace NextVpn;

public sealed class BoolToVisibilityConverter : IValueConverter
{
    /// <summary>Set to true to show the element when the bound value is false.</summary>
    public bool Invert { get; set; }

    public object Convert(object value, Type targetType, object parameter, string language)
    {
        var flag = value is bool b && b;
        if (Invert) flag = !flag;
        return flag ? Visibility.Visible : Visibility.Collapsed;
    }

    public object ConvertBack(object value, Type targetType, object parameter, string language) =>
        value is Visibility v && v == Visibility.Visible;
}

public sealed class LogLevelToBrushConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, string language)
    {
        var color = value switch
        {
            NoticeLevel.Error => Color.FromArgb(255, 255, 107, 107),
            NoticeLevel.Warning => Color.FromArgb(255, 242, 180, 65),
            _ => Color.FromArgb(255, 130, 200, 255)
        };
        return new SolidColorBrush(color);
    }

    public object ConvertBack(object value, Type targetType, object parameter, string language) =>
        throw new NotSupportedException();
}

/// <summary>Renders the selected-region tick only on the row that is actually selected.</summary>
public sealed class RegionSelectedConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, string language)
    {
        if (value is not string code || App.ViewModel is null) return Visibility.Collapsed;
        return code == App.ViewModel.SelectedRegion.Code ? Visibility.Visible : Visibility.Collapsed;
    }

    public object ConvertBack(object value, Type targetType, object parameter, string language) =>
        throw new NotSupportedException();
}
