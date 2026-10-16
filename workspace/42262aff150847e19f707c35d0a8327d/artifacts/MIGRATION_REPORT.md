# Migration report: inventory_orders_sample.xlsm

Generated 2026-10-15T19:28:46+00:00 by the migration platform.

## Summary

**The generated app builds.** It has not been tested beyond that.

- Generated app: `InventoryOrdersSample` (24 files, 2 stubs).
- Found in the VBA: 1 entities, 20 rules, 0 screens, 0 workflows, 0 reports.
- Flags: 0 blockers, 5 warnings, 6 notes.
- Model tokens used: 9,616.

## How to run

Requires the .NET 8 SDK.

```
cd app/InventoryOrdersSample
dotnet run
```

Open the address printed in the console. The app starts with no records: only the VBA logic was migrated, not the workbook's data.

## Build result

- .NET SDK 10.0.102
- Restore: ok. Build: ok.
- 0 compiler warning(s), 0 error(s).

## Needs your attention

- `RUL-010` ExportOrdersPDF is a stub (unsupported): Excel PDF export through COM (found by the rule check).
- `RUL-011` EmailLowStockReport is a stub (unsupported): COM automation of another application (found by the rule check).
- VBA procedure `modInventory.ExportLowStockCSV` is partial: File write (found by the rule check).
- VBA procedure `modInventory.ExportOrdersPDF` is unsupported: Excel PDF export through COM (found by the rule check).
- VBA procedure `modInventory.EmailLowStockReport` is unsupported: COM automation of another application (found by the rule check).
- VBA procedure `ThisWorkbook.Workbook_SheetChange` is partial: Worksheet_Change event cascade (found by the rule check).

Search the code for `MIGRATION-TODO` to find every place that needs a decision.

## Warnings

- **Warning** PARTIAL_FILE_WRITE `modInventory:140`: File write in ExportLowStockCSV (3 places: lines 140, 141, 144).
- **Warning** UNSUPPORTED_EXPORT_PDF `modInventory:152`: Excel PDF export through COM in ExportOrdersPDF.
- **Warning** UNSUPPORTED_COM_AUTOMATION `modInventory:158`: COM automation of another application in EmailLowStockReport.
- **Warning** UNSUPPORTED_WIN32_DECLARE `modUtils:4`: Win32 Declare call in the declarations of modUtils.
- **Warning** PARTIAL_WORKSHEET_CHANGE_EVENT `ThisWorkbook:17`: Worksheet_Change event cascade in Workbook_SheetChange.

## What is in this zip

- `app/`: the ASP.NET Core 8 Razor Pages solution (24 files; `bin`, `obj` and `.env` files are never included).
- `docs/`: the migration spec (Markdown and JSON), the code analysis, the generation manifest and the build results.
- `MIGRATION_REPORT.md`: this file.

## Limits of this migration

- Only VBA code was read. Sheet contents, named ranges, table definitions and UserForm layouts were not available.
- Generated logic comes from a language model. It is a starting point to review, not a verified port.
- PDF and Excel report output, and anything marked unsupported, are stubs.
