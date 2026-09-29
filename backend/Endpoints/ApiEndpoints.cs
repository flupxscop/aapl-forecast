using AaplForecast.Api.Contracts;
using AaplForecast.Api.Data;
using AaplForecast.Api.Services;
using System.Security.Cryptography;
using System.Text;
using Microsoft.EntityFrameworkCore;

namespace AaplForecast.Api.Endpoints;

public static class ApiEndpoints
{
    public static void MapApi(this WebApplication app)
    {
        var api = app.MapGroup("/api");

        api.MapGet("/health", () => Results.Ok(new { status = "ok", time = DateTime.UtcNow }));

        // Tells the web UI which features exist (precomputed = free hosting without the Python service).
        api.MapGet("/config", (ForecastService svc) =>
            Results.Ok(new { mode = svc.Precomputed ? "precomputed" : "live", maxHorizon = svc.Precomputed ? 90 : 365 }));

        // ------------------------------------------------------------------ tracked symbols
        api.MapGet("/symbols", async (AppDbContext db, CancellationToken ct) =>
            Results.Ok(await db.Symbols.AsNoTracking().OrderBy(s => s.SortOrder)
                .Select(s => new SymbolDto(s.Symbol, s.Name, s.DisplayTicker, s.Exchange, s.Currency,
                    s.NativeCurrency, s.KaggleDataset, s.YahooTicker))
                .ToListAsync(ct))).WithTags("Symbols");

        // One card per stock: last price, best model, latest forecast.
        api.MapGet("/overview", async (AppDbContext db, ForecastService svc, CancellationToken ct) =>
        {
            var symbols = await db.Symbols.AsNoTracking().OrderBy(s => s.SortOrder).ToListAsync(ct);
            var result = new List<OverviewDto>();
            foreach (var s in symbols)
            {
                var prices = db.StockPrices.AsNoTracking().Where(p => p.Symbol == s.Symbol);
                var rows = await prices.CountAsync(ct);
                // last ~3 months, newest first (also used for the sparkline)
                var recent = await prices.OrderByDescending(p => p.TradeDate).Take(66)
                    .Select(p => new { p.TradeDate, Px = p.AdjClose ?? p.Close }).ToListAsync(ct);
                var best = await db.ModelRuns.AsNoTracking().Where(r => r.Symbol == s.Symbol && r.IsBest)
                    .OrderByDescending(r => r.TrainedAt).FirstOrDefaultAsync(ct);
                var fc = await svc.GetLatestAsync(s.Symbol, null, ct);
                var fcLast = fc?.Points.LastOrDefault();

                double? lastPx = recent.Count > 0 ? recent[0].Px : (double?)null;
                double? chg = recent.Count > 1 ? (recent[0].Px / recent[1].Px - 1) * 100 : (double?)null;
                result.Add(new OverviewDto(
                    s.Symbol, s.Name, s.DisplayTicker, s.Exchange, s.NativeCurrency,
                    rows, recent.Count > 0 ? recent[0].TradeDate : (DateOnly?)null, lastPx, chg,
                    best?.ModelName, best?.Mape,
                    fc?.Model, fc?.Horizon, fcLast?.Date, fcLast?.Predicted,
                    fc is not null && fcLast is not null ? (fcLast.Predicted / fc.BaseClose - 1) * 100 : (double?)null,
                    recent.Select(x => Math.Round(x.Px, 4)).Reverse().ToList()));
            }
            return Results.Ok(result);
        }).WithTags("Symbols");

        // ------------------------------------------------------------------ stock data
        var stocks = api.MapGroup("/stocks/{symbol}").WithTags("Stocks");

        stocks.MapGet("/prices", async (string symbol, DateOnly? from, DateOnly? to, AppDbContext db, CancellationToken ct) =>
        {
            symbol = symbol.ToUpperInvariant();
            var q = db.StockPrices.AsNoTracking().Where(p => p.Symbol == symbol);
            if (from is not null) q = q.Where(p => p.TradeDate >= from.Value);
            if (to is not null) q = q.Where(p => p.TradeDate <= to.Value);
            var rows = await q.OrderBy(p => p.TradeDate)
                .Select(p => new PriceDto(p.TradeDate, p.Open, p.High, p.Low, p.Close, p.AdjClose, p.Volume))
                .ToListAsync(ct);
            return Results.Ok(rows);
        });

        stocks.MapGet("/summary", async (string symbol, AppDbContext db, CancellationToken ct) =>
        {
            symbol = symbol.ToUpperInvariant();
            var q = db.StockPrices.AsNoTracking().Where(p => p.Symbol == symbol);
            var count = await q.CountAsync(ct);
            if (count < 2) return Results.NotFound(new { error = $"No data for {symbol}. Run the ingest step first." });

            var first = await q.MinAsync(p => p.TradeDate, ct);
            var recent = await q.OrderByDescending(p => p.TradeDate).Take(252).ToListAsync(ct);
            double Px(StockPrice p) => p.AdjClose ?? p.Close;
            var last = recent[0];
            var prev = recent[1];
            var change = Px(last) - Px(prev);
            return Results.Ok(new SummaryDto(
                symbol, count, first, last.TradeDate, Px(last), Px(prev), change, change / Px(prev) * 100,
                recent.Max(p => p.High ?? Px(p)), recent.Min(p => p.Low ?? Px(p)),
                recent.Take(30).Average(p => (double)(p.Volume ?? 0))));
        });

        // ------------------------------------------------------------------ models
        var models = api.MapGroup("/models").WithTags("Models");

        models.MapGet("/", async (MlClient ml, CancellationToken ct) => Results.Ok(await ml.GetModelsAsync(ct)));

        models.MapGet("/{symbol}/metrics", async (string symbol, AppDbContext db, CancellationToken ct) =>
        {
            symbol = symbol.ToUpperInvariant();
            var runs = await db.ModelRuns.AsNoTracking().Where(r => r.Symbol == symbol)
                .OrderByDescending(r => r.TrainedAt).Take(100).ToListAsync(ct);
            // latest run of every model
            var latest = runs.GroupBy(r => r.ModelName).Select(g => g.First())
                .OrderBy(r => r.Mape)
                .Select(r => new ModelMetricDto(r.ModelName, r.TrainedAt, r.TrainStart, r.TrainEnd, r.TestDays,
                    r.Mae, r.Rmse, r.Mape, r.DirectionAcc, r.IsBest));
            return Results.Ok(latest);
        });

        // ------------------------------------------------------------------ forecasts
        var forecasts = api.MapGroup("/forecasts").WithTags("Forecasts");

        forecasts.MapPost("/", async (ForecastRequest req, ForecastService svc, CancellationToken ct) =>
        {
            if (req.Horizon is < 1 or > 365) return Results.BadRequest(new { error = "Horizon must be 1-365 days" });
            var dto = await svc.CreateAsync(req, ct);
            return Results.Created($"/api/forecasts/{dto.Id}", dto);
        }).RequireRateLimiting("forecast");

        forecasts.MapGet("/{id:long}", async (long id, ForecastService svc, CancellationToken ct) =>
            await svc.GetAsync(id, ct) is { } f ? Results.Ok(f) : Results.NotFound());

        forecasts.MapGet("/symbol/{symbol}/latest", async (string symbol, string? model, int? horizon, ForecastService svc, CancellationToken ct) =>
            await svc.GetLatestAsync(symbol.ToUpperInvariant(), model, ct, Math.Clamp(horizon ?? 30, 1, 365)) is { } f
                ? Results.Ok(f) : Results.NotFound());

        forecasts.MapGet("/symbol/{symbol}", async (string symbol, int? limit, AppDbContext db, CancellationToken ct) =>
        {
            symbol = symbol.ToUpperInvariant();
            var rows = await db.Forecasts.AsNoTracking().Where(f => f.Symbol == symbol)
                .OrderByDescending(f => f.CreatedAt).Take(Math.Clamp(limit ?? 20, 1, 200))
                .Select(f => new ForecastHeaderDto(f.Id, f.Symbol, f.ModelName, f.Horizon, f.BaseDate, f.CreatedAt))
                .ToListAsync(ct);
            return Results.Ok(rows);
        });

        // ------------------------------------------------------------------ admin (pipeline)
        // When AdminApiKey is set (always in production) every /api/admin call needs header X-Admin-Key.
        var admin = api.MapGroup("/admin").WithTags("Admin").RequireRateLimiting("admin").AddEndpointFilter(async (ctx, next) =>
        {
            var key = ctx.HttpContext.RequestServices.GetRequiredService<IConfiguration>()["AdminApiKey"];
            if (!string.IsNullOrEmpty(key))
            {
                var sent = Encoding.UTF8.GetBytes(ctx.HttpContext.Request.Headers["X-Admin-Key"].ToString());
                if (!CryptographicOperations.FixedTimeEquals(sent, Encoding.UTF8.GetBytes(key)))
                    return Results.Json(new { error = "รหัสผู้ดูแลไม่ถูกต้อง" }, statusCode: StatusCodes.Status401Unauthorized);
            }
            return await next(ctx);
        });

        // Lets the web UI check a key before running long jobs; also tells it whether a key is required.
        admin.MapGet("/check", (IConfiguration cfg) =>
            Results.Ok(new { ok = true, protectedByKey = !string.IsNullOrEmpty(cfg["AdminApiKey"]) }));

        static IResult BatchOnly() => Results.Json(
            new { error = "โหมดนี้อัปเดตข้อมูลด้วย GitHub Actions — กด Run workflow ในแท็บ Actions ของ repository" },
            statusCode: StatusCodes.Status503ServiceUnavailable);

        admin.MapPost("/ingest", async (IngestRequest? req, MlClient ml, ForecastService svc, CancellationToken ct) =>
            svc.Precomputed ? BatchOnly() : Results.Ok(await ml.IngestAsync(req ?? new IngestRequest(), ct)));

        admin.MapPost("/train", async (TrainRequest? req, MlClient ml, ForecastService svc, CancellationToken ct) =>
            svc.Precomputed ? BatchOnly() : Results.Ok(await ml.TrainAsync(req ?? new TrainRequest(), ct)));
    }
}
