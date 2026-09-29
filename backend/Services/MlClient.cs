using System.Net.Http.Json;
using System.Text.Json;
using AaplForecast.Api.Contracts;

namespace AaplForecast.Api.Services;

public class MlServiceException(int statusCode, string message) : Exception(message)
{
    public int StatusCode { get; } = statusCode;
}

/// <summary>Typed HTTP client for the Python FastAPI model service.</summary>
public class MlClient(HttpClient http)
{
    public Task<JsonElement> GetModelsAsync(CancellationToken ct) => SendAsync(HttpMethod.Get, "/models", null, ct);

    public Task<JsonElement> IngestAsync(IngestRequest req, CancellationToken ct) =>
        SendAsync(HttpMethod.Post, "/ingest", new { symbol = Blank(req.Symbol), dataset = Blank(req.Dataset) }, ct);

    public Task<JsonElement> TrainAsync(TrainRequest req, CancellationToken ct) =>
        SendAsync(HttpMethod.Post, "/train", new { symbol = Blank(req.Symbol), models = req.Models }, ct);

    public async Task<MlForecastResponse> ForecastAsync(ForecastRequest req, CancellationToken ct)
    {
        var json = await SendAsync(HttpMethod.Post, "/forecast",
            new { symbol = req.Symbol, model = req.Model, horizon = req.Horizon }, ct);
        return json.Deserialize<MlForecastResponse>()
               ?? throw new MlServiceException(502, "Empty forecast response from ML service");
    }

    /// <summary>Empty strings mean "not set" (e.g. ingest/train every symbol).</summary>
    private static string? Blank(string? s) => string.IsNullOrWhiteSpace(s) ? null : s.Trim();

    private async Task<JsonElement> SendAsync(HttpMethod method, string path, object? body, CancellationToken ct)
    {
        using var msg = new HttpRequestMessage(method, path);
        if (body is not null) msg.Content = JsonContent.Create(body);

        HttpResponseMessage res;
        try { res = await http.SendAsync(msg, ct); }
        catch (HttpRequestException e) { throw new MlServiceException(503, $"ML service unreachable: {e.Message}"); }

        var text = await res.Content.ReadAsStringAsync(ct);
        if (!res.IsSuccessStatusCode)
        {
            var detail = text;
            try { detail = JsonDocument.Parse(text).RootElement.GetProperty("detail").ToString(); } catch { /* raw text */ }
            throw new MlServiceException((int)res.StatusCode, detail);
        }
        return JsonDocument.Parse(text).RootElement.Clone();
    }
}
