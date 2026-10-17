# Migration report: Sample_Orders_Pricing.xlsm

Generated 2026-10-17T10:22:59+00:00 by the migration platform.

## Summary

**The generated app builds.** It has not been tested beyond that.

- Generated app: `SampleOrdersPricing` (31 files, 1 stubs).
- Found in the VBA: 2 entities, 22 rules, 0 screens, 0 workflows, 1 reports.
- Flags: 0 blockers, 4 warnings, 4 notes.
- Model tokens used: 41,140.

## How to run

Requires the .NET 8 SDK.

```
cd app/SampleOrdersPricing
dotnet run
```

Open the address printed in the console. The app starts with no records: only the VBA logic was migrated, not the workbook's data.

## Build result

- .NET SDK 8.0.426
- Restore: ok. Build: ok.
- 0 compiler warning(s), 0 error(s).

## Needs your attention

- `RPT-001` OrderSummaryReport is a stub (unsupported): Excel export needs a library such as ClosedXML. Add the package and implement this report.

Search the code for `MIGRATION-TODO` to find every place that needs a decision.

## Warnings

- **Warning** SPEC_OPEN_QUESTION `modPricing`: How are OrderLine records persisted to the Orders worksheet (column mapping for SKU, Quantity, UnitPrice, etc.)?
- **Warning** SPEC_OPEN_QUESTION `modInventory`: How do the Orders and Summary worksheets map to the InventoryItem entity or other entities (e.g., order lines, totals) referenced elsewhere in the application?
- **Warning** SPEC_OPEN_QUESTION `modReporting.BuildOrderSummary`: What are the specific meanings of columns A‑I in the Orders worksheet (e.g., which column holds OrderId, CustomerTier, Region, etc.)?
- **Warning** SPEC_OPEN_QUESTION `modReporting.ParseTier`: What are the defined values of the CustomerTier enum (e.g., tierSilver, tierGold, tierPlatinum, tierStandard) and their underlying type?

## What is in this zip

- `app/`: the ASP.NET Core 8 Razor Pages solution (31 files; `bin`, `obj` and `.env` files are never included).
- `docs/`: the migration spec (Markdown and JSON), the code analysis, the generation manifest and the build results.
- `MIGRATION_REPORT.md`: this file.

## Limits of this migration

- Only VBA code was read. Sheet contents, named ranges, table definitions and UserForm layouts were not available.
- Generated logic comes from a language model. It is a starting point to review, not a verified port.
- PDF and Excel report output, and anything marked unsupported, are stubs.
