using System.Globalization;

namespace SampleOrdersPricing.Infrastructure;

public static class Coerce
{
    public static T To<T>(object? value)
    {
        if (value is null) return default!;
        if (value is T same) return same;
        try
        {
            if (value is string text && string.IsNullOrWhiteSpace(text)) return default!;
            var target = Nullable.GetUnderlyingType(typeof(T)) ?? typeof(T);
            return (T)Convert.ChangeType(value, target, CultureInfo.InvariantCulture);
        }
        catch
        {
            return default!;
        }
    }
}
