using Microsoft.EntityFrameworkCore;

namespace AaplForecast.Api.Data;

/// <summary>Maps to the tables created by db/init/01_schema.sql (schema is owned by that script).</summary>
public class AppDbContext(DbContextOptions<AppDbContext> options) : DbContext(options)
{
    public DbSet<TrackedSymbol> Symbols => Set<TrackedSymbol>();
    public DbSet<StockPrice> StockPrices => Set<StockPrice>();
    public DbSet<ModelRun> ModelRuns => Set<ModelRun>();
    public DbSet<Forecast> Forecasts => Set<Forecast>();
    public DbSet<ForecastPoint> ForecastPoints => Set<ForecastPoint>();

    protected override void OnModelCreating(ModelBuilder b)
    {
        b.Entity<TrackedSymbol>(e =>
        {
            e.ToTable("symbols");
            e.HasKey(x => x.Symbol);
            e.Property(x => x.Symbol).HasColumnName("symbol");
            e.Property(x => x.Name).HasColumnName("name");
            e.Property(x => x.DisplayTicker).HasColumnName("display_ticker");
            e.Property(x => x.Exchange).HasColumnName("exchange");
            e.Property(x => x.Currency).HasColumnName("currency");
            e.Property(x => x.NativeCurrency).HasColumnName("native_currency");
            e.Property(x => x.KaggleDataset).HasColumnName("kaggle_dataset");
            e.Property(x => x.YahooTicker).HasColumnName("yahoo_ticker");
            e.Property(x => x.SortOrder).HasColumnName("sort_order");
        });

        b.Entity<StockPrice>(e =>
        {
            e.ToTable("stock_prices");
            e.HasKey(x => new { x.Symbol, x.TradeDate });
            e.Property(x => x.Symbol).HasColumnName("symbol");
            e.Property(x => x.TradeDate).HasColumnName("trade_date");
            e.Property(x => x.Open).HasColumnName("open");
            e.Property(x => x.High).HasColumnName("high");
            e.Property(x => x.Low).HasColumnName("low");
            e.Property(x => x.Close).HasColumnName("close");
            e.Property(x => x.AdjClose).HasColumnName("adj_close");
            e.Property(x => x.Volume).HasColumnName("volume");
            e.Property(x => x.Source).HasColumnName("source");
        });

        b.Entity<ModelRun>(e =>
        {
            e.ToTable("model_runs");
            e.HasKey(x => x.Id);
            e.Property(x => x.Id).HasColumnName("id");
            e.Property(x => x.Symbol).HasColumnName("symbol");
            e.Property(x => x.ModelName).HasColumnName("model_name");
            e.Property(x => x.TrainedAt).HasColumnName("trained_at");
            e.Property(x => x.TrainStart).HasColumnName("train_start");
            e.Property(x => x.TrainEnd).HasColumnName("train_end");
            e.Property(x => x.TestDays).HasColumnName("test_days");
            e.Property(x => x.Mae).HasColumnName("mae");
            e.Property(x => x.Rmse).HasColumnName("rmse");
            e.Property(x => x.Mape).HasColumnName("mape");
            e.Property(x => x.DirectionAcc).HasColumnName("direction_acc");
            e.Property(x => x.IsBest).HasColumnName("is_best");
            e.Property(x => x.Params).HasColumnName("params").HasColumnType("jsonb");
        });

        b.Entity<Forecast>(e =>
        {
            e.ToTable("forecasts");
            e.HasKey(x => x.Id);
            e.Property(x => x.Id).HasColumnName("id");
            e.Property(x => x.Symbol).HasColumnName("symbol");
            e.Property(x => x.ModelName).HasColumnName("model_name");
            e.Property(x => x.Horizon).HasColumnName("horizon");
            e.Property(x => x.BaseDate).HasColumnName("base_date");
            e.Property(x => x.BaseClose).HasColumnName("base_close");
            e.Property(x => x.CreatedAt).HasColumnName("created_at");
            e.HasMany(x => x.Points).WithOne().HasForeignKey(p => p.ForecastId).OnDelete(DeleteBehavior.Cascade);
        });

        b.Entity<ForecastPoint>(e =>
        {
            e.ToTable("forecast_points");
            e.HasKey(x => new { x.ForecastId, x.Step });
            e.Property(x => x.ForecastId).HasColumnName("forecast_id");
            e.Property(x => x.Step).HasColumnName("step");
            e.Property(x => x.TargetDate).HasColumnName("target_date");
            e.Property(x => x.Predicted).HasColumnName("predicted");
            e.Property(x => x.Lower).HasColumnName("lower");
            e.Property(x => x.Upper).HasColumnName("upper");
        });
    }
}
