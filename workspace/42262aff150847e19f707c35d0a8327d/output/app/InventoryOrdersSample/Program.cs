using InventoryOrdersSample.Infrastructure;
using InventoryOrdersSample.Services;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddRazorPages();
builder.Services.AddSingleton(typeof(IRepository<>), typeof(JsonRepository<>));
builder.Services.AddSingleton<BusinessRules>();

var app = builder.Build();

app.UseStaticFiles();
app.UseRouting();
app.MapRazorPages();

app.Run();
