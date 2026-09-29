using System.Threading.RateLimiting;
using AaplForecast.Api.Data;
using AaplForecast.Api.Endpoints;
using AaplForecast.Api.Services;
using Microsoft.AspNetCore.HttpOverrides;
using Microsoft.EntityFrameworkCore;

var builder = WebApplication.CreateBuilder(args);

// Hosts such as Render tell the app which port to listen on through $PORT.
if (Environment.GetEnvironmentVariable("PORT") is { Length: > 0 } port)
    builder.WebHost.UseUrls($"http://0.0.0.0:{port}");

builder.Services.AddDbContext<AppDbContext>(o =>
    o.UseNpgsql(ToNpgsql(builder.Configuration.GetConnectionString("Postgres"))));

builder.Services.AddHttpClient<MlClient>(c =>
{
    c.BaseAddress = new Uri(builder.Configuration["MlService:BaseUrl"] ?? "http://localhost:8000");
    c.Timeout = TimeSpan.FromMinutes(15); // training can take a while
});
builder.Services.AddScoped<ForecastService>();

var origins = (builder.Configuration["Cors:Origins"] ?? "http://localhost:3000")
    .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
builder.Services.AddCors(o => o.AddDefaultPolicy(p => p.WithOrigins(origins).AllowAnyHeader().AllowAnyMethod()));
builder.Services.AddOpenApi();
builder.Services.AddProblemDetails();

// In production the API sits behind Caddy on a private Docker network: trust its X-Forwarded-For
// so rate limits apply per visitor, not per proxy.
builder.Services.Configure<ForwardedHeadersOptions>(o =>
{
    o.ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto;
    o.KnownIPNetworks.Clear();
    o.KnownProxies.Clear();
});

// Per-IP limits: forecasts are cheap but not free; admin calls are also a password check.
static RateLimitPartition<string> PerIp(HttpContext ctx, int permits, TimeSpan window) =>
    RateLimitPartition.GetFixedWindowLimiter(
        ctx.Connection.RemoteIpAddress?.ToString() ?? "unknown",
        _ => new FixedWindowRateLimiterOptions { PermitLimit = permits, Window = window, QueueLimit = 0 });

builder.Services.AddRateLimiter(o =>
{
    o.RejectionStatusCode = StatusCodes.Status429TooManyRequests;
    o.AddPolicy("forecast", ctx => PerIp(ctx, builder.Configuration.GetValue("RateLimits:ForecastsPerMinute", 20), TimeSpan.FromMinutes(1)));
    o.AddPolicy("admin", ctx => PerIp(ctx, builder.Configuration.GetValue("RateLimits:AdminPerMinute", 10), TimeSpan.FromMinutes(1)));
});

var app = builder.Build();

app.UseForwardedHeaders();

// Turn ML-service errors into clean JSON responses with the ML service's status code.
app.Use(async (ctx, next) =>
{
    try { await next(); }
    catch (MlServiceException e)
    {
        ctx.Response.StatusCode = e.StatusCode;
        await ctx.Response.WriteAsJsonAsync(new { error = e.Message });
    }
});

app.UseCors();
app.UseRateLimiter();
app.MapOpenApi(); // GET /openapi/v1.json
app.MapApi();

app.Run();

// Accept both "Host=...;Username=..." and the postgresql://user:pass@host/db?sslmode=require URLs
// that hosted Postgres providers (Neon, Supabase, ...) show, so the same value works everywhere.
static string? ToNpgsql(string? cs)
{
    if (cs is null || !(cs.StartsWith("postgres://") || cs.StartsWith("postgresql://"))) return cs;
    var uri = new Uri(cs);
    var userInfo = uri.UserInfo.Split(':', 2);
    var b = new Npgsql.NpgsqlConnectionStringBuilder
    {
        Host = uri.Host,
        Port = uri.IsDefaultPort || uri.Port <= 0 ? 5432 : uri.Port,
        Database = Uri.UnescapeDataString(uri.AbsolutePath.TrimStart('/')),
        Username = Uri.UnescapeDataString(userInfo[0]),
        Password = userInfo.Length > 1 ? Uri.UnescapeDataString(userInfo[1]) : null,
    };
    // sslmode=require / verify-full / disable ... (hosted databases need SSL, so default to Require)
    var ssl = System.Web.HttpUtility.ParseQueryString(uri.Query)["sslmode"];
    b.SslMode = ssl is not null && Enum.TryParse<Npgsql.SslMode>(ssl.Replace("-", ""), true, out var mode)
        ? mode
        : Npgsql.SslMode.Require;
    return b.ConnectionString;
}
