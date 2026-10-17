using System.ComponentModel.DataAnnotations;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using SampleOrdersPricing.Infrastructure;
using SampleOrdersPricing.Models;
using SampleOrdersPricing.Services;

namespace SampleOrdersPricing.Pages.Entities;

public class InventoryItemModel : PageModel
{
    private readonly IRepository<InventoryItem> _repo;

    public InventoryItemModel(IRepository<InventoryItem> repo)
    {
        _repo = repo;
    }

    [BindProperty] public InventoryItem Item { get; set; } = new();
    public IReadOnlyList<InventoryItem> Items { get; set; } = new List<InventoryItem>();

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
