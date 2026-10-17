using System.Globalization;
using System.Text;
using SampleOrdersPricing.Infrastructure;
using SampleOrdersPricing.Models;

namespace SampleOrdersPricing.Services;

public partial class BusinessRules
{
    // RUL-001 GetTierDiscount. Source: modPricing.GetTierDiscount
    // Returns a discount rate based on the customer's tier: Silver = 5 %, Gold = 10 %, Platinum = 15 %, otherwise 0 %.
    public decimal GetTierDiscount(int tier)
    {
        if (tier == 1) return 0.05m;
        if (tier == 2) return 0.10m;
        if (tier == 3) return 0.15m;
        return 0m;
    }

    // RUL-002 GetVolumeDiscount. Source: modPricing.GetVolumeDiscount
    // Returns a discount rate based on the ordered quantity: ≥100 → 12 %, ≥50 → 8 %, ≥10 → 3 %, otherwise 0 %.
    public decimal GetVolumeDiscount(int qty)
    {
        if (qty >= 100) return 0.12m;
        if (qty >= 50) return 0.08m;
        if (qty >= 10) return 0.03m;
        return 0m;
    }

    // RUL-003 GetTaxRate. Source: modPricing.GetTaxRate
    // Returns the tax rate for a given region; specific rates for CA, NY, NJ, TX, zero for OR/MT/NH/DE, otherwise the default rate of 8 %.
    public decimal GetTaxRate(string region)
    {
        var r = region?.Trim().ToUpperInvariant();
        switch (r)
        {
            case "CA": return 0.0725m;
            case "NY": return 0.08875m;
            case "NJ": return 0.06625m;
            case "TX": return 0.0625m;
            case "OR":
            case "MT":
            case "NH":
            case "DE": return 0m;
            default: return 0.08m; // default tax rate 8%
        }
    }

    // RUL-004 CalculateLineTotal. Source: modPricing.CalculateLineTotal
    // Computes the line total by applying tier and volume discounts to the gross amount (quantity × unit price), capping the combined discount at 25 %, and rounding to two decimals.
    public decimal CalculateLineTotal(OrderLine line, int tier)
    {
        decimal gross = line.Quantity * line.UnitPrice;
        decimal discountRate = GetTierDiscount(tier) + GetVolumeDiscount(line.Quantity);
        const decimal MAX_TOTAL_DISCOUNT = 0.25m;
        if (discountRate > MAX_TOTAL_DISCOUNT) discountRate = MAX_TOTAL_DISCOUNT;
        return Math.Round(gross * (1 - discountRate), 2, MidpointRounding.ToEven);
    }

    // RUL-005 CalculateShipping. Source: modPricing.CalculateShipping
    // Determines shipping cost based on subtotal, weight, and whether express shipping is selected; free shipping when subtotal ≥ 150 and not express. Weight tiers: ≤1 kg → 4.99, ≤5 kg → 9.99, ≤20 kg → 19.99, above 20 kg → 19.99 + 0.75 × (excess kg). Express shipping doubles the cost. Result rounded to two decimals.
    public decimal CalculateShipping(decimal subtotal, decimal weightKg, bool expressShipping)
    {
        const decimal FREE_SHIPPING_THRESHOLD = 150m;
        if (subtotal >= FREE_SHIPPING_THRESHOLD && !expressShipping) return 0m;
        decimal cost;
        if (weightKg <= 1m) cost = 4.99m;
        else if (weightKg <= 5m) cost = 9.99m;
        else if (weightKg <= 20m) cost = 19.99m;
        else cost = 19.99m + (weightKg - 20m) * 0.75m;
        if (expressShipping) cost *= 2m;
        return Math.Round(cost, 2, MidpointRounding.ToEven);
    }

    // RUL-006 ApplyPromoCode. Source: modPricing.ApplyPromoCode
    // Applies a promotional discount to the subtotal: WELCOME10 gives 10 % off, SAVE20 subtracts $20 if subtotal ≥ 200, otherwise no change.
    public decimal ApplyPromoCode(decimal subtotal, string promoCode)
    {
        var code = promoCode?.Trim().ToUpperInvariant();
        if (code == "WELCOME10")
            return subtotal * 0.90m;
        if (code == "SAVE20")
            return subtotal >= 200m ? subtotal - 20m : subtotal;
        return subtotal; // empty or unknown code
    }

    // RUL-007 CalculateOrderTotal. Source: modPricing.CalculateOrderTotal
    // Aggregates line totals for all order lines, applies any promotional code, adds shipping cost, computes tax based on region, and returns the final order total.
    public decimal CalculateOrderTotal(List<OrderLine> lines, int tier, string region, decimal weightKg, bool expressShipping, string promoCode)
    {
        decimal subtotal = 0m;
        foreach (var line in lines)
            subtotal += CalculateLineTotal(line, tier);
        subtotal = Math.Round(ApplyPromoCode(subtotal, promoCode), 2, MidpointRounding.ToEven);
        decimal shipping = CalculateShipping(subtotal, weightKg, expressShipping);
        decimal tax = Math.Round(subtotal * GetTaxRate(region), 2, MidpointRounding.ToEven);
        return subtotal + shipping + tax;
    }

    // RUL-008 NeedsReorder. Source: modInventory.NeedsReorder
    // Determines whether inventory should be reordered by comparing on‑hand quantity to the reorder point and by projecting stock after lead time using average daily usage.
    public bool NeedsReorder(int onHand, int reorderPoint, int leadTimeDays, decimal avgDailyUsage)
    {
        decimal projected = onHand - (leadTimeDays * avgDailyUsage);
        return (onHand <= reorderPoint) || (projected <= 0m);
    }

    // RUL-009 SuggestedOrderQty. Source: modInventory.SuggestedOrderQty
    // Computes the recommended purchase quantity, rounding up to the nearest pack size and adding a safety buffer based on lead time and average daily usage.
    public int SuggestedOrderQty(int onHand, int leadTimeDays, decimal avgDailyUsage, int packSize)
    {
        if (packSize <= 0) packSize = 1;
        const int SAFETY_DAYS = 0; // MIGRATION-TODO: define actual safety days
        double target = (double)avgDailyUsage * (leadTimeDays + SAFETY_DAYS);
        double needed = target - onHand;
        if (needed <= 0) return 0;
        int packs = (int)Math.Floor(needed / packSize);
        if (packs * packSize < needed) packs++;
        return packs * packSize;
    }

    // RUL-010 ClassifyAbc. Source: modInventory.ClassifyAbc
    // Assigns an ABC category (A, B, or C) to an item based on its share of total annual value; >=20% = A, >=5% = B, otherwise C.
    public string ClassifyAbc(decimal annualValue, decimal totalValue)
    {
        if (totalValue <= 0) return "C";
        decimal share = annualValue / totalValue;
        if (share >= 0.2m) return "A";
        else if (share >= 0.05m) return "B";
        else return "C";
    }

    // RUL-011 SafeDivide. Source: modInventory.SafeDivide
    // Divides numerator by denominator and returns 0 if division would cause an error (e.g., divide‑by‑zero).
    public decimal SafeDivide(decimal numerator, decimal denominator)
    {
        if (denominator == 0) return 0;
        try { return numerator / denominator; } catch { return 0; }
    }

    // RUL-012 SumPositive. Source: modInventory.SumPositive
    // Aggregates only the positive numbers from an array of numeric values.
    public decimal SumPositive(List<decimal> values)
    {
        decimal total = 0;
        foreach (var v in values) if (v > 0) total += v;
        return total;
    }

    // RUL-013 DaysOfStock. Source: modInventory.DaysOfStock
    // Estimates how many days current inventory will last given average daily usage; returns a large sentinel value when usage is zero.
    public int DaysOfStock(int onHand, decimal avgDailyUsage)
    {
        if (avgDailyUsage <= 0) return 9999;
        int days = 0;
        int onHandInt = onHand;
        while (onHandInt > 0 && days < 9999)
        {
            int usage = (int)Math.Floor((double)avgDailyUsage + 0.5);
            onHandInt -= usage;
            days++;
            if (onHandInt <= 0) break;
        }
        return days;
    }

    // RUL-014 MonthlyPayment. Source: modFinance.MonthlyPayment
    // Calculates the monthly payment for a loan given principal, annual interest rate (percent) and term in years, using the standard amortizing loan formula and rounding to two decimals.
    public decimal MonthlyPayment(decimal principal, decimal annualRatePct, int years)
    {
        int n = years * 12;
        if (n <= 0) return 0;
        decimal r = annualRatePct / 100m / 12m;
        if (r == 0)
            return Math.Round(principal / n, 2, MidpointRounding.AwayFromZero);
        else
            return Math.Round(principal * r / (1 - (decimal)Math.Pow((double)(1 + r), -n)), 2, MidpointRounding.AwayFromZero);
    }

    // RUL-015 TotalInterest. Source: modFinance.TotalInterest
    // Computes total interest paid over the life of a loan by multiplying the monthly payment by the total number of payments and subtracting the principal, rounding to two decimals.
    public decimal TotalInterest(decimal principal, decimal annualRatePct, int years)
    {
        decimal payment = MonthlyPayment(principal, annualRatePct, years);
        return Math.Round(payment * years * 12 - principal, 2, MidpointRounding.AwayFromZero);
    }

    // RUL-016 BuildAmortization. Source: modFinance.BuildAmortization
    // Generates a full amortization schedule as a two‑dimensional array (period, interest, principal, remaining balance) for each month of the loan term, rounding monetary values to two decimals.
    public List<string> BuildAmortization(decimal principal, decimal annualRatePct, int years)
    {
        int n = years * 12;
        decimal payment = MonthlyPayment(principal, annualRatePct, years);
        decimal balance = principal;
        var schedule = new List<string>();
        for (int i = 1; i <= n; i++)
        {
            decimal interest = Math.Round(balance * annualRatePct / 100m / 12m, 2, MidpointRounding.AwayFromZero);
            if (i == n) payment = balance + interest;
            decimal principalPortion = payment - interest;
            balance = Math.Round(balance - principalPortion, 2, MidpointRounding.AwayFromZero);
            schedule.Add($"{i},{interest},{principalPortion},{balance}");
        }
        return schedule;
    }

    // RUL-017 NetPresentValue. Source: modFinance.NetPresentValue
    // Calculates the net present value of a series of cash flows discounted at a given annual rate (percent), summing each cash flow divided by (1+rate) raised to the period offset, rounding to two decimals.
    public decimal NetPresentValue(decimal ratePct, List<string> cashFlows)
    {
        decimal npv = 0m;
        decimal rateFactor = 1m + ratePct / 100m;
        for (int i = 0; i < cashFlows.Count; i++)
        {
            decimal cf = decimal.Parse(cashFlows[i], CultureInfo.InvariantCulture);
            decimal divisor = (decimal)Math.Pow((double)rateFactor, i);
            npv += cf / divisor;
        }
        return Math.Round(npv, 2, MidpointRounding.AwayFromZero);
    }

    // RUL-018 NormalizeSku. Source: modText.NormalizeSku
    // Converts a raw SKU to uppercase, replaces spaces and underscores with hyphens, and truncates to 12 characters
    public string NormalizeSku(string rawSku)
    {
        string s = rawSku.Trim().ToUpperInvariant();
        s = s.Replace(" ", "-").Replace("_", "-");
        if (s.Length > 12) s = s.Substring(0, 12);
        return s;
    }

    // RUL-019 IsValidEmail. Source: modText.IsValidEmail
    // Checks that an email address contains exactly one '@' and a '.' after the '@' and before the end of the string
    public bool IsValidEmail(string email)
    {
        email = email.Trim();
        int atPos = email.IndexOf('@');
        if (atPos < 1) return false;
        if (email.IndexOf('@', atPos + 1) != -1) return false;
        int dotPos = email.LastIndexOf('.');
        return dotPos > atPos + 1 && dotPos < email.Length - 1;
    }

    // RUL-020 ToTitleCase. Source: modText.ToTitleCase
    // Converts a string to title case by capitalizing the first letter of each word
    public string ToTitleCase(string text)
    {
        text = text.Trim();
        string[] words = text.ToLowerInvariant().Split(' ', StringSplitOptions.None);
        for (int i = 0; i < words.Length; i++)
        {
            if (words[i].Length > 0)
            {
                words[i] = char.ToUpperInvariant(words[i][0]) + (words[i].Length > 1 ? words[i].Substring(1) : string.Empty);
            }
        }
        return string.Join(" ", words);
    }

    // RUL-021 IsValidLuhn. Source: modText.IsValidLuhn
    // Validates a numeric string using the Luhn algorithm (checksum)
    public bool IsValidLuhn(string digits)
    {
        digits = digits.Replace(" ", "");
        if (digits.Length < 2) return false;
        int total = 0;
        bool doubleIt = false;
        for (int i = digits.Length - 1; i >= 0; i--)
        {
            char c = digits[i];
            if (c < '0' || c > '9') return false;
            int d = c - '0';
            if (doubleIt)
            {
                d *= 2;
                if (d > 9) d -= 9;
            }
            total += d;
            doubleIt = !doubleIt;
        }
        return total % 10 == 0;
    }

    // RUL-022 ParseTier. Source: modReporting.ParseTier
    // Converts a tier description string to the corresponding CustomerTier enum value using case‑insensitive matching
    public string ParseTier(string text)
    {
        string t = text.Trim().ToLowerInvariant();
        switch (t)
        {
            case "silver": return "Silver";
            case "gold": return "Gold";
            case "platinum": return "Platinum";
            default: return "Standard";
        }
    }
}
