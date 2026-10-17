namespace SampleOrdersPricing.Models;

// ENT-001 OrderLine (explicit in the VBA code)
// Represents a single line item in an order, containing product SKU, quantity, and unit price.
// Source: modPricing
public class OrderLine : IEntity
{
    public int Id { get; set; }
    public string Sku { get; set; } = "";
    public int Quantity { get; set; }
    public decimal UnitPrice { get; set; }
}
