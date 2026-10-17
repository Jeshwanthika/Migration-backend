namespace SampleOrdersPricing.Models;

// ENT-002 InventoryItem (inferred)
// Represents an inventory item with stock levels, usage metrics and valuation used for reorder calculations and ABC classification.
// Source: modInventory.NeedsReorder, modInventory.SuggestedOrderQty, modInventory.ClassifyAbc, modInventory.DaysOfStock
public class InventoryItem : IEntity
{
    public int Id { get; set; }
    public int OnHand { get; set; }
    public int ReorderPoint { get; set; }
    public int LeadTimeDays { get; set; }
    public decimal AvgDailyUsage { get; set; }
    public int PackSize { get; set; }
    public decimal AnnualValue { get; set; }
    public decimal TotalValue { get; set; }
}
