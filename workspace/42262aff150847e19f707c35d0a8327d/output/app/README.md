# Inventory Orders Sample

Migrated from `inventory_orders_sample.xlsm` by the migration platform. Only the VBA logic was migrated.
No workbook data was carried over: records start empty and are kept in `Data/*.json`.

## Run

Requires the .NET 8 SDK.

```
cd InventoryOrdersSample
dotnet run
```

Open the address printed in the console. To build only: `dotnet build` in this folder.

## What is in here

- `InventoryOrdersSample/Models`: one class per record type (1).
- `InventoryOrdersSample/Infrastructure`: JSON file repository and small helpers.
- `InventoryOrdersSample/Services/BusinessRules.*.cs`: rules (20), workflows (0) and reports (0).
- `InventoryOrdersSample/Pages`: Razor Pages for home, records (1), screens (0), workflows and reports.

## Still to do

- `RUL-010` ExportOrdersPDF (unsupported): Excel PDF export through COM (found by the rule check).
- `RUL-011` EmailLowStockReport (unsupported): COM automation of another application (found by the rule check).

Search the code for `MIGRATION-TODO` to find every place that needs attention.
