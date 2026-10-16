# Migration specification

Source: `inventory_orders_sample.xlsm`

> Only the VBA code was analyzed. Workbook data, cell contents and UserForm layouts were not available.
> Entities, fields and screen controls are inferred from how the code uses sheets, ranges, forms and message boxes.
> Every element lists the procedures it came from in source_ref.

1 entities, 20 rules, 0 screens, 0 workflows, 0 reports, 4 procedures needing attention.

## Entities

### ENT-001 Item (inferred, supported)

Placeholder record from the mock provider.

| Field | Type | Required | Notes |
|---|---|---|---|
| Name | string | no |  |
| Amount | decimal | no |  |

Source: `modInventory.AddProduct`, `modUtils.FormatSku`, `clsProduct.Sku`, `ThisWorkbook.Workbook_Open`

## Business rules

### RUL-001 AddProduct (calculation, supported)

Mock rule for AddProduct.

Source: `modInventory.AddProduct`

### RUL-002 FindProductRow (calculation, supported)

Mock rule for FindProductRow.

Source: `modInventory.FindProductRow`

### RUL-003 LookupPrice (calculation, supported)

Mock rule for LookupPrice.

Source: `modInventory.LookupPrice`

### RUL-004 GetDiscount (calculation, supported)

Mock rule for GetDiscount.

Source: `modInventory.GetDiscount`

### RUL-005 CalcOrderTotal (calculation, supported)

Mock rule for CalcOrderTotal.

Source: `modInventory.CalcOrderTotal`

### RUL-006 PlaceOrder (calculation, supported)

Mock rule for PlaceOrder.

Source: `modInventory.PlaceOrder`

### RUL-007 CheckReorder (calculation, supported)

Mock rule for CheckReorder.

Source: `modInventory.CheckReorder`

### RUL-008 RefreshStockStatus (calculation, supported)

Mock rule for RefreshStockStatus.

Source: `modInventory.RefreshStockStatus`

### RUL-009 ExportLowStockCSV (calculation, partial)

Mock rule for ExportLowStockCSV.

Source: `modInventory.ExportLowStockCSV`

### RUL-010 ExportOrdersPDF (calculation, unsupported)

Mock rule for ExportOrdersPDF.

Source: `modInventory.ExportOrdersPDF`

### RUL-011 EmailLowStockReport (calculation, unsupported)

Mock rule for EmailLowStockReport.

Source: `modInventory.EmailLowStockReport`

### RUL-012 FormatSku (calculation, supported)

Mock rule for FormatSku.

Source: `modUtils.FormatSku`

### RUL-013 IsValidQty (calculation, supported)

Mock rule for IsValidQty.

Source: `modUtils.IsValidQty`

### RUL-014 PauseBriefly (calculation, supported)

Mock rule for PauseBriefly.

Source: `modUtils.PauseBriefly`

### RUL-015 Sku (calculation, supported)

Mock rule for Sku.

Source: `clsProduct.Sku`, `clsProduct.Sku.Let`

### RUL-016 Stock (calculation, supported)

Mock rule for Stock.

Source: `clsProduct.Stock`, `clsProduct.Stock.Let`

### RUL-017 ReorderLevel (calculation, supported)

Mock rule for ReorderLevel.

Source: `clsProduct.ReorderLevel`

### RUL-018 IsLowStock (calculation, supported)

Mock rule for IsLowStock.

Source: `clsProduct.IsLowStock`

### RUL-019 WorkbookOpen (calculation, supported)

Mock rule for Workbook_Open.

Source: `ThisWorkbook.Workbook_Open`

### RUL-020 WorkbookSheetChange (calculation, partial)

Mock rule for Workbook_SheetChange.

Source: `ThisWorkbook.Workbook_SheetChange`

## Screens

None found.

## Workflows

None found.

## Reports and exports

None found.

## Procedures that need attention

| Procedure | Lines | Level | Reason |
|---|---|---|---|
| `modInventory.ExportLowStockCSV` | 130-149 | partial | File write (found by the rule check). |
| `modInventory.ExportOrdersPDF` | 151-153 | unsupported | Excel PDF export through COM (found by the rule check). |
| `modInventory.EmailLowStockReport` | 155-164 | unsupported | COM automation of another application (found by the rule check). |
| `ThisWorkbook.Workbook_SheetChange` | 17-28 | partial | Worksheet_Change event cascade (found by the rule check). |

## Flags

No warnings.

