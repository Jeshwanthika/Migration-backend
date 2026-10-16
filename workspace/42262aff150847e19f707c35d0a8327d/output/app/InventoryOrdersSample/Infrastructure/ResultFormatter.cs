using System.Text.Json;

namespace InventoryOrdersSample.Infrastructure;

public static class ResultFormatter
{
    private static readonly JsonSerializerOptions Options = new() { WriteIndented = true, IncludeFields = true };

    public static string Format(object? value)
    {
        if (value is null) return "";
        if (value is string text) return text;
        try
        {
            return JsonSerializer.Serialize(value, Options);
        }
        catch
        {
            return value.ToString() ?? "";
        }
    }
}
