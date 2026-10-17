using System.ComponentModel.DataAnnotations;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using SampleOrdersPricing.Infrastructure;
using SampleOrdersPricing.Models;
using SampleOrdersPricing.Services;

namespace SampleOrdersPricing.Pages;

public class ReportsModel : PageModel
{
    private readonly BusinessRules _rules;

    public ReportsModel(BusinessRules rules)
    {
        _rules = rules;
    }

    public string Message { get; set; } = "";

    public void OnGet()
    {
    }

    public IActionResult OnGetOrderSummaryReport()
    {
        try
        {
            var file = _rules.OrderSummaryReport();
            return File(file.Content, file.ContentType, file.FileName);
        }
        catch (NotImplementedException ex)
        {
            Message = ex.Message;
        }
        catch (Exception ex)
        {
            Message = "Something went wrong: " + ex.Message;
        }
        return Page();
    }
}
