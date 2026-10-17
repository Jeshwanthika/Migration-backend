# Sample Orders Pricing

Migrated from `Sample_Orders_Pricing.xlsm` by the migration platform. Only the VBA logic was migrated.
No workbook data was carried over: records start empty and are kept in `Data/*.json`.

## Run

Requires the .NET 8 SDK.

```
cd SampleOrdersPricing
dotnet run
```

Open the address printed in the console. To build only: `dotnet build` in this folder.

## What is in here

- `SampleOrdersPricing/Models`: one class per record type (2).
- `SampleOrdersPricing/Infrastructure`: JSON file repository and small helpers.
- `SampleOrdersPricing/Services/BusinessRules.*.cs`: rules (22), workflows (0) and reports (1).
- `SampleOrdersPricing/Pages`: Razor Pages for home, records (2), screens (0), workflows and reports.

## Still to do

- `RPT-001` OrderSummaryReport (unsupported): Excel export needs a library such as ClosedXML. Add the package and implement this report.

Search the code for `MIGRATION-TODO` to find every place that needs attention.
