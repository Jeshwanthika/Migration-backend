"""The fixed project scaffold (FR-GN1): solution, project, startup, repository, shared Razor files.

Everything here is plain text with __APP__ replaced by the root namespace. None of it is written
by the LLM, so the scaffold compiles the same way for every workbook.
"""
from __future__ import annotations

import uuid

from app.plugins.xlsm_to_aspnetcore.gen.csharp import razor_text

SLN = '''Microsoft Visual Studio Solution File, Format Version 12.00
# Visual Studio Version 17
VisualStudioVersion = 17.0.31903.59
MinimumVisualStudioVersion = 10.0.40219.1
Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "__APP__", "__APP__\\__APP__.csproj", "{__GUID__}"
EndProject
Global
	GlobalSection(SolutionConfigurationPlatforms) = preSolution
		Debug|Any CPU = Debug|Any CPU
		Release|Any CPU = Release|Any CPU
	EndGlobalSection
	GlobalSection(ProjectConfigurationPlatforms) = postSolution
		{__GUID__}.Debug|Any CPU.ActiveCfg = Debug|Any CPU
		{__GUID__}.Debug|Any CPU.Build.0 = Debug|Any CPU
		{__GUID__}.Release|Any CPU.ActiveCfg = Release|Any CPU
		{__GUID__}.Release|Any CPU.Build.0 = Release|Any CPU
	EndGlobalSection
EndGlobal
'''

CSPROJ = '''<Project Sdk="Microsoft.NET.Sdk.Web">

  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <RootNamespace>__APP__</RootNamespace>
    <AssemblyName>__APP__</AssemblyName>
  </PropertyGroup>

</Project>
'''

PROGRAM = '''using __APP__.Infrastructure;
using __APP__.Services;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddRazorPages();
builder.Services.AddSingleton(typeof(IRepository<>), typeof(JsonRepository<>));
builder.Services.AddSingleton<BusinessRules>();

var app = builder.Build();

app.UseStaticFiles();
app.UseRouting();
app.MapRazorPages();

app.Run();
'''

APPSETTINGS = '''{
  "Logging": {
    "LogLevel": {
      "Default": "Information",
      "Microsoft.AspNetCore": "Warning"
    }
  },
  "AllowedHosts": "*",
  "Export": {
    "Folder": "Exports"
  }
}
'''

GITIGNORE = "bin/\nobj/\n.vs/\n*.user\n"

IENTITY = '''namespace __APP__.Models;

public interface IEntity
{
    int Id { get; set; }
}
'''

IREPOSITORY = '''using __APP__.Models;

namespace __APP__.Infrastructure;

public interface IRepository<T> where T : class, IEntity
{
    IReadOnlyList<T> GetAll();
    T? GetById(int id);
    T Add(T item);
    bool Update(T item);
    bool Delete(int id);
    void Clear();
}
'''

JSON_REPOSITORY = '''using System.Text.Json;
using __APP__.Models;

namespace __APP__.Infrastructure;

public class JsonRepository<T> : IRepository<T> where T : class, IEntity
{
    private static readonly JsonSerializerOptions Options = new() { WriteIndented = true };
    private readonly object _lock = new();
    private readonly string _path;
    private List<T>? _items;

    public JsonRepository(IWebHostEnvironment env)
    {
        var folder = System.IO.Path.Combine(env.ContentRootPath, "Data");
        System.IO.Directory.CreateDirectory(folder);
        _path = System.IO.Path.Combine(folder, typeof(T).Name + ".json");
    }

    private List<T> Load()
    {
        if (_items != null) return _items;
        if (System.IO.File.Exists(_path))
        {
            var text = System.IO.File.ReadAllText(_path);
            _items = string.IsNullOrWhiteSpace(text)
                ? new List<T>()
                : JsonSerializer.Deserialize<List<T>>(text, Options) ?? new List<T>();
        }
        else
        {
            _items = new List<T>();
        }
        return _items;
    }

    private void Save()
    {
        System.IO.File.WriteAllText(_path, JsonSerializer.Serialize(_items, Options));
    }

    public IReadOnlyList<T> GetAll()
    {
        lock (_lock) { return Load().ToList(); }
    }

    public T? GetById(int id)
    {
        lock (_lock) { return Load().FirstOrDefault(x => x.Id == id); }
    }

    public T Add(T item)
    {
        lock (_lock)
        {
            var list = Load();
            item.Id = list.Count == 0 ? 1 : list.Max(x => x.Id) + 1;
            list.Add(item);
            Save();
            return item;
        }
    }

    public bool Update(T item)
    {
        lock (_lock)
        {
            var list = Load();
            var index = list.FindIndex(x => x.Id == item.Id);
            if (index < 0) return false;
            list[index] = item;
            Save();
            return true;
        }
    }

    public bool Delete(int id)
    {
        lock (_lock)
        {
            var list = Load();
            var removed = list.RemoveAll(x => x.Id == id) > 0;
            if (removed) Save();
            return removed;
        }
    }

    public void Clear()
    {
        lock (_lock)
        {
            Load().Clear();
            Save();
        }
    }
}
'''

COERCE = '''using System.Globalization;

namespace __APP__.Infrastructure;

public static class Coerce
{
    public static T To<T>(object? value)
    {
        if (value is null) return default!;
        if (value is T same) return same;
        try
        {
            if (value is string text && string.IsNullOrWhiteSpace(text)) return default!;
            var target = Nullable.GetUnderlyingType(typeof(T)) ?? typeof(T);
            return (T)Convert.ChangeType(value, target, CultureInfo.InvariantCulture);
        }
        catch
        {
            return default!;
        }
    }
}
'''

RESULT_FORMATTER = '''using System.Text.Json;

namespace __APP__.Infrastructure;

public static class ResultFormatter
{
    private static readonly JsonSerializerOptions Options = new() { WriteIndented = true, IncludeFields = true };

    public static string Format(object? value)
    {
        if (value is null) return "";
        if (value is string text) return text;
        try
        {
            return JsonSerializer.Serialize(value, Options);
        }
        catch
        {
            return value.ToString() ?? "";
        }
    }
}
'''

REPORT_FILE = '''namespace __APP__.Infrastructure;

public record ReportFile(byte[] Content, string ContentType, string FileName);
'''

BUSINESS_RULES_BASE = '''using System.Globalization;
using System.Text;
using __APP__.Infrastructure;
using __APP__.Models;

namespace __APP__.Services;

// The business logic of the migrated workbook. Rules, workflows and reports are added as
// partial class files next to this one.
public partial class BusinessRules
{
    private readonly IServiceProvider _services;

    public BusinessRules(IServiceProvider services, IConfiguration configuration)
    {
        _services = services;
        ExportFolder = configuration["Export:Folder"] ?? "Exports";
    }

    protected string ExportFolder { get; }

    protected IRepository<T> Repo<T>() where T : class, IEntity
        => _services.GetRequiredService<IRepository<T>>();
}
'''

VIEW_IMPORTS = '''@using __APP__
@namespace __APP__.Pages
@addTagHelper *, Microsoft.AspNetCore.Mvc.TagHelpers
'''

VIEW_START = '''@{
    Layout = "_Layout";
}
'''

LAYOUT = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>@ViewData["Title"] - __TITLE__</title>
    <link rel="stylesheet" href="~/css/site.css" asp-append-version="true" />
</head>
<body>
    <header>
        <a class="brand" asp-page="/Index">__TITLE__</a>
        <nav>
__NAV__
        </nav>
    </header>
    <main>
        @RenderBody()
    </main>
</body>
</html>
'''

SITE_CSS = '''body { font-family: system-ui, sans-serif; margin: 0; color: #1d1d1f; background: #fafafa; }
header { display: flex; flex-wrap: wrap; align-items: center; gap: 16px; padding: 12px 24px; background: #1f2937; }
header a { color: #f3f4f6; text-decoration: none; }
header a:hover { text-decoration: underline; }
.brand { font-weight: 700; margin-right: 12px; }
nav { display: flex; flex-wrap: wrap; gap: 14px; }
main { max-width: 1000px; margin: 0 auto; padding: 24px; }
h1 { font-size: 24px; }
h2 { font-size: 18px; margin-top: 28px; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #d1d5db; }
label { display: block; margin: 10px 0 4px; font-weight: 600; }
input, select { font: inherit; padding: 6px 8px; min-width: 240px; }
button, .button { font: inherit; padding: 6px 14px; margin: 8px 8px 0 0; cursor: pointer; }
.message { padding: 10px 14px; border-radius: 6px; background: #e0f2fe; margin: 12px 0; }
.todo { background: #fef3c7; }
pre { background: #f3f4f6; padding: 10px; border-radius: 6px; overflow-x: auto; }
.muted { color: #6b7280; }
@media (prefers-color-scheme: dark) {
  body { color: #e5e7eb; background: #111827; }
  th, td { border-color: #374151; }
  pre { background: #1f2937; }
  .message { background: #1e3a5f; }
  .todo { background: #4a3b10; }
}
'''


def app_guid(app: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{app}.migration")).upper()


def _fill(text: str, app: str, **extra) -> str:
    text = text.replace("__APP__", app)
    for key, value in extra.items():
        text = text.replace(f"__{key}__", value)
    return text


def scaffold_files(app: str, title: str, nav_links: list) -> dict:
    """Return {relative path: content}. nav_links: list of (label, razor page path like '/Workflows')."""
    nav = "\n".join(f'            <a asp-page="{page}">{razor_text(label)}</a>' for label, page in nav_links)
    p = f"{app}/"
    return {
        f"{app}.sln": _fill(SLN, app, GUID=app_guid(app)),
        ".gitignore": GITIGNORE,
        f"{p}{app}.csproj": _fill(CSPROJ, app),
        f"{p}Program.cs": _fill(PROGRAM, app),
        f"{p}appsettings.json": APPSETTINGS,
        f"{p}Models/IEntity.cs": _fill(IENTITY, app),
        f"{p}Infrastructure/IRepository.cs": _fill(IREPOSITORY, app),
        f"{p}Infrastructure/JsonRepository.cs": _fill(JSON_REPOSITORY, app),
        f"{p}Infrastructure/Coerce.cs": _fill(COERCE, app),
        f"{p}Infrastructure/ResultFormatter.cs": _fill(RESULT_FORMATTER, app),
        f"{p}Infrastructure/ReportFile.cs": _fill(REPORT_FILE, app),
        f"{p}Services/BusinessRules.cs": _fill(BUSINESS_RULES_BASE, app),
        f"{p}Pages/_ViewImports.cshtml": _fill(VIEW_IMPORTS, app),
        f"{p}Pages/_ViewStart.cshtml": VIEW_START,
        f"{p}Pages/Shared/_Layout.cshtml": _fill(LAYOUT, app, TITLE=razor_text(title), NAV=nav),
        f"{p}wwwroot/css/site.css": SITE_CSS,
    }
