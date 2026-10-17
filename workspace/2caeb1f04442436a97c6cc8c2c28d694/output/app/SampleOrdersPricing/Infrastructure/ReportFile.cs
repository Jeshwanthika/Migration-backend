namespace SampleOrdersPricing.Infrastructure;

public record ReportFile(byte[] Content, string ContentType, string FileName);
