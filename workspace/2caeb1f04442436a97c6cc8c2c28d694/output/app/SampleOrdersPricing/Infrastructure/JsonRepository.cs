using System.Text.Json;
using SampleOrdersPricing.Models;

namespace SampleOrdersPricing.Infrastructure;

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
