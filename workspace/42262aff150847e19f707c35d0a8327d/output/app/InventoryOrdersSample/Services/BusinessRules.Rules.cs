using System.Globalization;
using System.Text;
using InventoryOrdersSample.Infrastructure;
using InventoryOrdersSample.Models;

namespace InventoryOrdersSample.Services;

public partial class BusinessRules
{
    // RUL-001 AddProduct. Source: modInventory.AddProduct
    // Mock rule for AddProduct.
    public void AddProduct()
    {
        throw new NotImplementedException("Placeholder from the mock provider.");
    }

    // RUL-002 FindProductRow. Source: modInventory.FindProductRow
    // Mock rule for FindProductRow.
    public void FindProductRow()
    {
        throw new NotImplementedException("Placeholder from the mock provider.");
    }

    // RUL-003 LookupPrice. Source: modInventory.LookupPrice
    // Mock rule for LookupPrice.
    public void LookupPrice()
    {
        throw new NotImplementedException("Placeholder from the mock provider.");
    }

    // RUL-004 GetDiscount. Source: modInventory.GetDiscount
    // Mock rule for GetDiscount.
    public void GetDiscount()
    {
        throw new NotImplementedException("Placeholder from the mock provider.");
    }

    // RUL-005 CalcOrderTotal. Source: modInventory.CalcOrderTotal
    // Mock rule for CalcOrderTotal.
    public void CalcOrderTotal()
    {
        throw new NotImplementedException("Placeholder from the mock provider.");
    }

    // RUL-006 PlaceOrder. Source: modInventory.PlaceOrder
    // Mock rule for PlaceOrder.
    public void PlaceOrder()
    {
        throw new NotImplementedException("Placeholder from the mock provider.");
    }

    // RUL-007 CheckReorder. Source: modInventory.CheckReorder
    // Mock rule for CheckReorder.
    public void CheckReorder()
    {
        throw new NotImplementedException("Placeholder from the mock provider.");
    }

    // RUL-008 RefreshStockStatus. Source: modInventory.RefreshStockStatus
    // Mock rule for RefreshStockStatus.
    public void RefreshStockStatus()
    {
        throw new NotImplementedException("Placeholder from the mock provider.");
    }

    // RUL-009 ExportLowStockCSV. Source: modInventory.ExportLowStockCSV
    // Mock rule for ExportLowStockCSV.
    // MIGRATION-TODO [PARTIAL-RUL-009]: some of the original VBA could only be partly migrated. Review the result.
    public void ExportLowStockCSV()
    {
        throw new NotImplementedException("Placeholder from the mock provider.");
    }

    // RUL-010 ExportOrdersPDF. Source: modInventory.ExportOrdersPDF
    // Mock rule for ExportOrdersPDF.
    // MIGRATION-TODO [UNSUPPORTED-RUL-010]: Excel PDF export through COM (found by the rule check).
    // Original VBA, modInventory.ExportOrdersPDF, lines 151-153:
    //   Public Sub ExportOrdersPDF()
    //       ThisWorkbook.Worksheets("Orders").ExportAsFixedFormat Type:=xlTypePDF, Filename:=ThisWorkbook.Path & "\orders.pdf"
    //   End Sub
    public void ExportOrdersPDF()
    {
        throw new NotImplementedException("MIGRATION-TODO [UNSUPPORTED-RUL-010] ExportOrdersPDF: Excel PDF export through COM (found by the rule check).");
    }

    // RUL-011 EmailLowStockReport. Source: modInventory.EmailLowStockReport
    // Mock rule for EmailLowStockReport.
    // MIGRATION-TODO [UNSUPPORTED-RUL-011]: COM automation of another application (found by the rule check).
    // Original VBA, modInventory.EmailLowStockReport, lines 155-164:
    //   Public Sub EmailLowStockReport()
    //       Dim outlookApp As Object
    //       Dim mail As Object
    //       Set outlookApp = CreateObject("Outlook.Application")
    //       Set mail = outlookApp.CreateItem(0)
    //       mail.To = "purchasing@example.com"
    //       mail.Subject = "Low stock report"
    //       mail.Body = "See the attached low stock list."
    //       mail.Send
    //   End Sub
    public void EmailLowStockReport()
    {
        throw new NotImplementedException("MIGRATION-TODO [UNSUPPORTED-RUL-011] EmailLowStockReport: COM automation of another application (found by the rule check).");
    }

    // RUL-012 FormatSku. Source: modUtils.FormatSku
    // Mock rule for FormatSku.
    public void FormatSku()
    {
        throw new NotImplementedException("Placeholder from the mock provider.");
    }

    // RUL-013 IsValidQty. Source: modUtils.IsValidQty
    // Mock rule for IsValidQty.
    public void IsValidQty()
    {
        throw new NotImplementedException("Placeholder from the mock provider.");
    }

    // RUL-014 PauseBriefly. Source: modUtils.PauseBriefly
    // Mock rule for PauseBriefly.
    public void PauseBriefly()
    {
        throw new NotImplementedException("Placeholder from the mock provider.");
    }

    // RUL-015 Sku. Source: clsProduct.Sku, clsProduct.Sku.Let
    // Mock rule for Sku.
    public void Sku()
    {
        throw new NotImplementedException("Placeholder from the mock provider.");
    }

    // RUL-016 Stock. Source: clsProduct.Stock, clsProduct.Stock.Let
    // Mock rule for Stock.
    public void Stock()
    {
        throw new NotImplementedException("Placeholder from the mock provider.");
    }

    // RUL-017 ReorderLevel. Source: clsProduct.ReorderLevel
    // Mock rule for ReorderLevel.
    public void ReorderLevel()
    {
        throw new NotImplementedException("Placeholder from the mock provider.");
    }

    // RUL-018 IsLowStock. Source: clsProduct.IsLowStock
    // Mock rule for IsLowStock.
    public void IsLowStock()
    {
        throw new NotImplementedException("Placeholder from the mock provider.");
    }

    // RUL-019 WorkbookOpen. Source: ThisWorkbook.Workbook_Open
    // Mock rule for Workbook_Open.
    public void WorkbookOpen()
    {
        throw new NotImplementedException("Placeholder from the mock provider.");
    }

    // RUL-020 WorkbookSheetChange. Source: ThisWorkbook.Workbook_SheetChange
    // Mock rule for Workbook_SheetChange.
    // MIGRATION-TODO [PARTIAL-RUL-020]: some of the original VBA could only be partly migrated. Review the result.
    public void WorkbookSheetChange()
    {
        throw new NotImplementedException("Placeholder from the mock provider.");
    }
}
