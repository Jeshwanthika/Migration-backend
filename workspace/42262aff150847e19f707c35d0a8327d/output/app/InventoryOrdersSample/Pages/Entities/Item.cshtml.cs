using System.ComponentModel.DataAnnotations;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using InventoryOrdersSample.Infrastructure;
using InventoryOrdersSample.Models;
using InventoryOrdersSample.Services;

namespace InventoryOrdersSample.Pages.Entities;

public class ItemModel : PageModel
{
    private readonly IRepository<Item> _repo;

    public ItemModel(IRepository<Item> repo)
    {
        _repo = repo;
    }

    [BindProperty] public Item Item { get; set; } = new();
    public IReadOnlyList<Item> Items { get; set; } = new List<Item>();

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
