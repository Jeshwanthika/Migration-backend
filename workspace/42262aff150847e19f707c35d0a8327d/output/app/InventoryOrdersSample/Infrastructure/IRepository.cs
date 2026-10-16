using InventoryOrdersSample.Models;

namespace InventoryOrdersSample.Infrastructure;

public interface IRepository<T> where T : class, IEntity
{
    IReadOnlyList<T> GetAll();
    T? GetById(int id);
    T Add(T item);
    bool Update(T item);
    bool Delete(int id);
    void Clear();
}
