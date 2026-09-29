using System.Text.Json.Serialization;

namespace AaplForecast.Api.Contracts;

// ---- API contracts (camelCase JSON to the frontend) ----
public record PriceDto(DateOnly Date, double? Open, double? High, double? Low, double Close, double? AdjClose, long? Volume);

public record SummaryDto(
    string Symbol, int Rows, DateOnly FirstDate, DateOnly LastDate,
    double LastClose, double PrevClose, double Change, double ChangePct,
    double High52w, double Low52w, double AvgVolume30d);

public record ForecastRequest(string Symbol = "AAPL", string Model = "auto", int Horizon = 30);

public record ForecastPointDto(int Step, DateOnly Date, double Predicted, double Lower, double Upper, double? Actual);

public record ForecastDto(
    long Id, string Symbol, string Model, int Horizon, DateOnly BaseDate, double BaseClose,
    DateTime CreatedAt, IReadOnlyList<ForecastPointDto> Points);

public record ForecastHeaderDto(long Id, string Symbol, string Model, int Horizon, DateOnly BaseDate, DateTime CreatedAt);

public record ModelMetricDto(
    string Model, DateTime TrainedAt, DateOnly? TrainStart, DateOnly? TrainEnd, int? TestDays,
    double? Mae, double? Rmse, double? Mape, double? DirectionAcc, bool IsBest);

/// <summary>Symbol null/empty = every tracked stock.</summary>
public record IngestRequest(string? Symbol = null, string? Dataset = null);
/// <summary>Symbol null/empty = every tracked stock.</summary>
public record TrainRequest(string? Symbol = null, List<string>? Models = null);

public record SymbolDto(string Symbol, string Name, string DisplayTicker, string Exchange,
    string Currency, string NativeCurrency, string? KaggleDataset, string? YahooTicker);

public record OverviewDto(
    string Symbol, string Name, string DisplayTicker, string Exchange, string NativeCurrency,
    int Rows, DateOnly? LastDate, double? LastClose, double? ChangePct,
    string? BestModel, double? BestMape,
    string? ForecastModel, int? ForecastHorizon, DateOnly? ForecastDate, double? ForecastPrice, double? ForecastChangePct,
    IReadOnlyList<double> Spark);

// ---- ML service wire format (snake_case) ----
public record MlForecastPoint(
    [property: JsonPropertyName("step")] int Step,
    [property: JsonPropertyName("date")] DateOnly Date,
    [property: JsonPropertyName("predicted")] double Predicted,
    [property: JsonPropertyName("lower")] double Lower,
    [property: JsonPropertyName("upper")] double Upper);

public record MlForecastResponse(
    [property: JsonPropertyName("symbol")] string Symbol,
    [property: JsonPropertyName("model")] string Model,
    [property: JsonPropertyName("horizon")] int Horizon,
    [property: JsonPropertyName("base_date")] DateOnly BaseDate,
    [property: JsonPropertyName("base_close")] double BaseClose,
    [property: JsonPropertyName("points")] List<MlForecastPoint> Points);
