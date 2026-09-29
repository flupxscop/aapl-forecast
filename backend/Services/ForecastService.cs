using AaplForecast.Api.Contracts;
using AaplForecast.Api.Data;
using Microsoft.EntityFrameworkCore;

namespace AaplForecast.Api.Services;

public class ForecastService(AppDbContext db, MlClient ml, IConfiguration config)
{
    /// <summary>
    /// "precomputed" (free hosting): forecasts are produced by the daily batch job and only read here,
    /// no Python service is needed at runtime. Anything else ("live"): forecasts are computed on request.
    /// </summary>
    public bool Precomputed => string.Equals(config["Forecasting:Mode"], "precomputed", StringComparison.OrdinalIgnoreCase);

    /// <summary>Ask the ML service for a forecast, persist it, return it (or read the stored one in precomputed mode).</summary>
    public async Task<ForecastDto> CreateAsync(ForecastRequest req, CancellationToken ct)
    {
        if (Precomputed)
            return await GetStoredAsync(req.Symbol.ToUpperInvariant(), req.Model, req.Horizon, ct)
                   ?? throw new MlServiceException(404,
                       $"ยังไม่มีค่าประมาณการ {req.Horizon} วันสำหรับ {req.Symbol} — รอรอบอัปเดตรายวันถัดไป");

        var res = await ml.ForecastAsync(req with { Symbol = req.Symbol.ToUpperInvariant() }, ct);
        var entity = new Forecast
        {
            Symbol = res.Symbol,
            ModelName = res.Model,
            Horizon = res.Horizon,
            BaseDate = res.BaseDate,
            BaseClose = res.BaseClose,
            CreatedAt = DateTime.UtcNow,
            Points = res.Points.Select(p => new ForecastPoint
            {
                Step = p.Step, TargetDate = p.Date, Predicted = p.Predicted, Lower = p.Lower, Upper = p.Upper
            }).ToList()
        };
        db.Forecasts.Add(entity);
        await db.SaveChangesAsync(ct);
        return await ToDtoAsync(entity, ct);
    }

    public async Task<ForecastDto?> GetAsync(long id, CancellationToken ct)
    {
        var f = await db.Forecasts.AsNoTracking().Include(x => x.Points).FirstOrDefaultAsync(x => x.Id == id, ct);
        return f is null ? null : await ToDtoAsync(f, ct);
    }

    public async Task<ForecastDto?> GetLatestAsync(string symbol, string? model, CancellationToken ct, int horizon = 30)
    {
        if (Precomputed) return await GetStoredAsync(symbol, model, horizon, ct);

        var q = db.Forecasts.AsNoTracking().Include(x => x.Points).Where(x => x.Symbol == symbol);
        if (!string.IsNullOrWhiteSpace(model) && model != "auto") q = q.Where(x => x.ModelName == model);
        var f = await q.OrderByDescending(x => x.CreatedAt).FirstOrDefaultAsync(ct);
        return f is null ? null : await ToDtoAsync(f, ct);
    }

    /// <summary>
    /// Newest stored forecast for the model ("auto" = the current best model) covering at least
    /// <paramref name="horizon"/> days, cut to that horizon. Every model forecasts step by step, so the
    /// first N days of a 90-day path are exactly the N-day forecast.
    /// </summary>
    public async Task<ForecastDto?> GetStoredAsync(string symbol, string? model, int horizon, CancellationToken ct)
    {
        var name = string.IsNullOrWhiteSpace(model) || model == "auto" ? await BestModelAsync(symbol, ct) : model;
        var q = db.Forecasts.AsNoTracking().Include(f => f.Points)
            .Where(f => f.Symbol == symbol && f.Horizon >= horizon);
        if (name is not null) q = q.Where(f => f.ModelName == name);
        var f = await q.OrderByDescending(f => f.BaseDate).ThenByDescending(f => f.CreatedAt).FirstOrDefaultAsync(ct);
        if (f is null) return null;
        var dto = await ToDtoAsync(f, ct);
        return dto with { Horizon = horizon, Points = dto.Points.Take(horizon).ToList() };
    }

    private Task<string?> BestModelAsync(string symbol, CancellationToken ct) =>
        db.ModelRuns.AsNoTracking().Where(r => r.Symbol == symbol && r.IsBest)
            .OrderByDescending(r => r.TrainedAt).Select(r => (string?)r.ModelName).FirstOrDefaultAsync(ct);

    /// <summary>Attach the real closing price to every forecast day that has already happened.</summary>
    private async Task<ForecastDto> ToDtoAsync(Forecast f, CancellationToken ct)
    {
        var dates = f.Points.Select(p => p.TargetDate).ToList();
        var actuals = await db.StockPrices.AsNoTracking()
            .Where(p => p.Symbol == f.Symbol && dates.Contains(p.TradeDate))
            .ToDictionaryAsync(p => p.TradeDate, p => p.AdjClose ?? p.Close, ct);

        var points = f.Points.OrderBy(p => p.Step)
            .Select(p => new ForecastPointDto(p.Step, p.TargetDate, p.Predicted, p.Lower, p.Upper,
                actuals.TryGetValue(p.TargetDate, out var a) ? a : null))
            .ToList();
        return new ForecastDto(f.Id, f.Symbol, f.ModelName, f.Horizon, f.BaseDate, f.BaseClose, f.CreatedAt, points);
    }
}
