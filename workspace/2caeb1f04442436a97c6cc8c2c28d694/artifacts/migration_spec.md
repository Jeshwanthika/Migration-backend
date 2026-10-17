# Migration specification

Source: `Sample_Orders_Pricing.xlsm`

> Only the VBA code was analyzed. Workbook data, cell contents and UserForm layouts were not available.
> Entities, fields and screen controls are inferred from how the code uses sheets, ranges, forms and message boxes.
> Every element lists the procedures it came from in source_ref.

2 entities, 22 rules, 0 screens, 0 workflows, 1 reports, 0 procedures needing attention.

## Entities

### ENT-001 OrderLine (explicit in the code, supported)

Represents a single line item in an order, containing product SKU, quantity, and unit price.

| Field | Type | Required | Notes |
|---|---|---|---|
| Sku | string | yes | Corresponds to the SKU field in the OrderLine type |
| Quantity | int | yes | Corresponds to the Quantity field in the OrderLine type |
| UnitPrice | decimal | yes | Corresponds to the UnitPrice field in the OrderLine type |

Source: `modPricing`

### ENT-002 InventoryItem (inferred, supported)

Represents an inventory item with stock levels, usage metrics and valuation used for reorder calculations and ABC classification.

| Field | Type | Required | Notes |
|---|---|---|---|
| OnHand | int | yes | Current quantity on hand, used in NeedsReorder, SuggestedOrderQty, DaysOfStock |
| ReorderPoint | int | yes | Threshold quantity that triggers a reorder, used in NeedsReorder |
| LeadTimeDays | int | yes | Supplier lead time in days, used in NeedsReorder and SuggestedOrderQty |
| AvgDailyUsage | decimal | yes | Average daily consumption, used in multiple calculations |
| PackSize | int | yes | Quantity per purchase pack, used in SuggestedOrderQty |
| AnnualValue | decimal | yes | Yearly monetary value of the item, used in ClassifyAbc |
| TotalValue | decimal | yes | Total value of all items for ABC share calculation |

Source: `modInventory.NeedsReorder`, `modInventory.SuggestedOrderQty`, `modInventory.ClassifyAbc`, `modInventory.DaysOfStock`

## Business rules

### RUL-001 GetTierDiscount (calculation, supported)

Returns a discount rate based on the customer's tier: Silver = 5 %, Gold = 10 %, Platinum = 15 %, otherwise 0 %.

Inputs: tier (int)
Outputs: discountRate (decimal)

Source: `modPricing.GetTierDiscount`

### RUL-002 GetVolumeDiscount (calculation, supported)

Returns a discount rate based on the ordered quantity: ≥100 → 12 %, ≥50 → 8 %, ≥10 → 3 %, otherwise 0 %.

Inputs: qty (int)
Outputs: discountRate (decimal)

Source: `modPricing.GetVolumeDiscount`

### RUL-003 GetTaxRate (calculation, supported)

Returns the tax rate for a given region; specific rates for CA, NY, NJ, TX, zero for OR/MT/NH/DE, otherwise the default rate of 8 %.

Inputs: region (string)
Outputs: taxRate (decimal)

Source: `modPricing.GetTaxRate`

### RUL-004 CalculateLineTotal (calculation, supported)

Computes the line total by applying tier and volume discounts to the gross amount (quantity × unit price), capping the combined discount at 25 %, and rounding to two decimals.

Inputs: line (OrderLine), tier (int)
Outputs: lineTotal (decimal)
Entities: OrderLine

Source: `modPricing.CalculateLineTotal`

### RUL-005 CalculateShipping (calculation, supported)

Determines shipping cost based on subtotal, weight, and whether express shipping is selected; free shipping when subtotal ≥ 150 and not express. Weight tiers: ≤1 kg → 4.99, ≤5 kg → 9.99, ≤20 kg → 19.99, above 20 kg → 19.99 + 0.75 × (excess kg). Express shipping doubles the cost. Result rounded to two decimals.

Inputs: subtotal (decimal), weightKg (decimal), expressShipping (bool)
Outputs: shippingCost (decimal)

Source: `modPricing.CalculateShipping`

### RUL-006 ApplyPromoCode (calculation, supported)

Applies a promotional discount to the subtotal: WELCOME10 gives 10 % off, SAVE20 subtracts $20 if subtotal ≥ 200, otherwise no change.

Inputs: subtotal (decimal), promoCode (string)
Outputs: adjustedSubtotal (decimal)

Source: `modPricing.ApplyPromoCode`

### RUL-007 CalculateOrderTotal (calculation, supported)

Aggregates line totals for all order lines, applies any promotional code, adds shipping cost, computes tax based on region, and returns the final order total.

Inputs: lines (OrderLine[]), tier (int), region (string), weightKg (decimal), expressShipping (bool), promoCode (string)
Outputs: orderTotal (decimal)
Entities: OrderLine

Source: `modPricing.CalculateOrderTotal`

### RUL-008 NeedsReorder (calculation, supported)

Determines whether inventory should be reordered by comparing on‑hand quantity to the reorder point and by projecting stock after lead time using average daily usage.

Inputs: onHand (int), reorderPoint (int), leadTimeDays (int), avgDailyUsage (decimal)
Outputs: needsReorder (bool)
Entities: InventoryItem

Source: `modInventory.NeedsReorder`

### RUL-009 SuggestedOrderQty (calculation, supported)

Computes the recommended purchase quantity, rounding up to the nearest pack size and adding a safety buffer based on lead time and average daily usage.

Inputs: onHand (int), leadTimeDays (int), avgDailyUsage (decimal), packSize (int)
Outputs: orderQty (int)
Entities: InventoryItem

Source: `modInventory.SuggestedOrderQty`

### RUL-010 ClassifyAbc (calculation, supported)

Assigns an ABC category (A, B, or C) to an item based on its share of total annual value; >=20% = A, >=5% = B, otherwise C.

Inputs: annualValue (decimal), totalValue (decimal)
Outputs: category (string)
Entities: InventoryItem

Source: `modInventory.ClassifyAbc`

### RUL-011 SafeDivide (calculation, supported)

Divides numerator by denominator and returns 0 if division would cause an error (e.g., divide‑by‑zero).

Inputs: numerator (decimal), denominator (decimal)
Outputs: result (decimal)

Source: `modInventory.SafeDivide`

### RUL-012 SumPositive (calculation, supported)

Aggregates only the positive numbers from an array of numeric values.

Inputs: values (decimal[])
Outputs: total (decimal)

Source: `modInventory.SumPositive`

### RUL-013 DaysOfStock (calculation, supported)

Estimates how many days current inventory will last given average daily usage; returns a large sentinel value when usage is zero.

Inputs: onHand (int), avgDailyUsage (decimal)
Outputs: days (int)
Entities: InventoryItem

Source: `modInventory.DaysOfStock`

### RUL-014 MonthlyPayment (calculation, supported)

Calculates the monthly payment for a loan given principal, annual interest rate (percent) and term in years, using the standard amortizing loan formula and rounding to two decimals.

Inputs: principal (decimal), annualRatePct (decimal), years (int)
Outputs: monthlyPayment (decimal)

Source: `modFinance.MonthlyPayment`

### RUL-015 TotalInterest (calculation, supported)

Computes total interest paid over the life of a loan by multiplying the monthly payment by the total number of payments and subtracting the principal, rounding to two decimals.

Inputs: principal (decimal), annualRatePct (decimal), years (int)
Outputs: totalInterest (decimal)

Source: `modFinance.TotalInterest`

### RUL-016 BuildAmortization (calculation, supported)

Generates a full amortization schedule as a two‑dimensional array (period, interest, principal, remaining balance) for each month of the loan term, rounding monetary values to two decimals.

Inputs: principal (decimal), annualRatePct (decimal), years (int)
Outputs: schedule (array)

Source: `modFinance.BuildAmortization`

### RUL-017 NetPresentValue (calculation, supported)

Calculates the net present value of a series of cash flows discounted at a given annual rate (percent), summing each cash flow divided by (1+rate) raised to the period offset, rounding to two decimals.

Inputs: ratePct (decimal), cashFlows (array)
Outputs: npv (decimal)

Source: `modFinance.NetPresentValue`

### RUL-018 NormalizeSku (other, supported)

Converts a raw SKU to uppercase, replaces spaces and underscores with hyphens, and truncates to 12 characters

Inputs: rawSku (string)
Outputs: result (string)

Source: `modText.NormalizeSku`

### RUL-019 IsValidEmail (validation, supported)

Checks that an email address contains exactly one '@' and a '.' after the '@' and before the end of the string

Inputs: email (string)
Outputs: isValid (bool)

Source: `modText.IsValidEmail`

### RUL-020 ToTitleCase (other, supported)

Converts a string to title case by capitalizing the first letter of each word

Inputs: text (string)
Outputs: result (string)

Source: `modText.ToTitleCase`

### RUL-021 IsValidLuhn (validation, supported)

Validates a numeric string using the Luhn algorithm (checksum)

Inputs: digits (string)
Outputs: isValid (bool)

Source: `modText.IsValidLuhn`

### RUL-022 ParseTier (lookup, supported)

Converts a tier description string to the corresponding CustomerTier enum value using case‑insensitive matching

Inputs: text (string)
Outputs: tier (enum)

Source: `modReporting.ParseTier`

## Screens

None found.

## Workflows

None found.

## Reports and exports

### RPT-001 OrderSummary (xlsx, supported)

Generates a summary sheet listing each order (OrderId, Sku, Region, Total) and a grand total for all processed orders

Data from: OrderLine

Source: `modReporting.BuildOrderSummary`

## Procedures that need attention

None. Every procedure is fully supported.

## Flags

- **Warning** SPEC_OPEN_QUESTION (`modPricing`): How are OrderLine records persisted to the Orders worksheet (column mapping for SKU, Quantity, UnitPrice, etc.)?
- **Warning** SPEC_OPEN_QUESTION (`modInventory`): How do the Orders and Summary worksheets map to the InventoryItem entity or other entities (e.g., order lines, totals) referenced elsewhere in the application?
- **Warning** SPEC_OPEN_QUESTION (`modReporting.BuildOrderSummary`): What are the specific meanings of columns A‑I in the Orders worksheet (e.g., which column holds OrderId, CustomerTier, Region, etc.)?
- **Warning** SPEC_OPEN_QUESTION (`modReporting.ParseTier`): What are the defined values of the CustomerTier enum (e.g., tierSilver, tierGold, tierPlatinum, tierStandard) and their underlying type?
