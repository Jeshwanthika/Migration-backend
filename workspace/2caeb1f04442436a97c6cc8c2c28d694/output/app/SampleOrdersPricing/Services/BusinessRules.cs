using System.Globalization;
using System.Text;
using SampleOrdersPricing.Infrastructure;
using SampleOrdersPricing.Models;

namespace SampleOrdersPricing.Services;

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
