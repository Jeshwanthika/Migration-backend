using System.ComponentModel.DataAnnotations;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using SampleOrdersPricing.Infrastructure;
using SampleOrdersPricing.Models;
using SampleOrdersPricing.Services;

namespace SampleOrdersPricing.Pages.Entities;

public class OrderLineModel : PageModel
{
    private readonly IRepository<OrderLine> _repo;

    public OrderLineModel(IRepository<OrderLine> repo)
    {
        _repo = repo;
    }

    [BindProperty] public OrderLine Item { get; set; } = new();
    public IReadOnlyList<OrderLine> Items { get; set; } = new List<OrderLine>();

    public void OnGet()
    {
        Items = _repo.GetAll();
    }

    public IActionResult OnPostAdd()
    {
        Item.Id = 0;
        _repo.Add(Item);
        return RedirectToPage();
    }

    public IActionResult OnPostDelete(int id)
    {
        _repo.Delete(id);
        return RedirectToPage();
    }
}
