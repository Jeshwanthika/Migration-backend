namespace InventoryOrdersSample.Models;

// ENT-001 Item (inferred)
// Placeholder record from the mock provider.
// Source: modInventory.AddProduct, modUtils.FormatSku, clsProduct.Sku, ThisWorkbook.Workbook_Open
public class Item : IEntity
{
    public int Id { get; set; }
    public string Name { get; set; } = "";
    public decimal Amount { get; set; }
}
