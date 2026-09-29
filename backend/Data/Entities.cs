namespace AaplForecast.Api.Data;

public class TrackedSymbol
{
    public string Symbol { get; set; } = "";
    public string Name { get; set; } = "";
    public string DisplayTicker { get; set; } = "";
    public string Exchange { get; set; } = "";
    public string Currency { get; set; } = "USD";
    public string NativeCurrency { get; set; } = "USD";
    public string? KaggleDataset { get; set; }
    public string? YahooTicker { get; set; }
    public int SortOrder { get; set; }
}

public class StockPrice
{
    public string Symbol { get; set; } = "";
    public DateOnly TradeDate { get; set; }
    public double? Open { get; set; }
    public double? High { get; set; }
    public double? Low { get; set; }
    public double Close { get; set; }
    public double? AdjClose { get; set; }
    public long? Volume { get; set; }
    public string? Source { get; set; }
}

public class ModelRun
{
    public long Id { get; set; }
    public string Symbol { get; set; } = "";
    public string ModelName { get; set; } = "";
    public DateTime TrainedAt { get; set; }
    public DateOnly? TrainStart { get; set; }
    public DateOnly? TrainEnd { get; set; }
    public int? TestDays { get; set; }
    public double? Mae { get; set; }
    public double? Rmse { get; set; }
    public double? Mape { get; set; }
    public double? DirectionAcc { get; set; }
    public bool IsBest { get; set; }
    public string? Params { get; set; }
}

public class Forecast
{
    public long Id { get; set; }
    public string Symbol { get; set; } = "";
    public string ModelName { get; set; } = "";
    public int Horizon { get; set; }
    public DateOnly BaseDate { get; set; }
    public double BaseClose { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public List<ForecastPoint> Points { get; set; } = new();
}

public class ForecastPoint
{
    public long ForecastId { get; set; }
    public int Step { get; set; }
    public DateOnly TargetDate { get; set; }
    public double Predicted { get; set; }
    public double Lower { get; set; }
    public double Upper { get; set; }
}
