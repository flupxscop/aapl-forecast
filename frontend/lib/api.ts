// Typed client for the .NET backend.
// "/" = same origin (production, behind the Caddy reverse proxy); unset = local dev backend.
const RAW_API_URL = process.env.NEXT_PUBLIC_API_URL;
export const API_URL = !RAW_API_URL ? "http://localhost:5080" : RAW_API_URL.replace(/\/+$/, "");

export interface Price {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number;
  adjClose: number | null;
  volume: number | null;
}

export interface Summary {
  symbol: string;
  rows: number;
  firstDate: string;
  lastDate: string;
  lastClose: number;
  prevClose: number;
  change: number;
  changePct: number;
  high52w: number;
  low52w: number;
  avgVolume30d: number;
}

export interface ForecastPoint {
  step: number;
  date: string;
  predicted: number;
  lower: number;
  upper: number;
  actual: number | null;
}

export interface Forecast {
  id: number;
  symbol: string;
  model: string;
  horizon: number;
  baseDate: string;
  baseClose: number;
  createdAt: string;
  points: ForecastPoint[];
}

export interface ModelMetric {
  model: string;
  trainedAt: string;
  trainStart: string | null;
  trainEnd: string | null;
  testDays: number | null;
  mae: number | null;
  rmse: number | null;
  mape: number | null;
  directionAcc: number | null;
  isBest: boolean;
}

export interface SymbolInfo {
  symbol: string;
  name: string;
  displayTicker: string;
  exchange: string;
  currency: string;
  nativeCurrency: string;
  kaggleDataset: string | null;
  yahooTicker: string | null;
}

export interface Overview {
  symbol: string;
  name: string;
  displayTicker: string;
  exchange: string;
  nativeCurrency: string;
  rows: number;
  lastDate: string | null;
  lastClose: number | null;
  changePct: number | null;
  bestModel: string | null;
  bestMape: number | null;
  forecastModel: string | null;
  forecastHorizon: number | null;
  forecastDate: string | null;
  forecastPrice: number | null;
  forecastChangePct: number | null;
  /** last ~66 daily closes, oldest first */
  spark: number[];
}

export interface IngestResult {
  symbol: string;
  rows: number;
  sources: string[];
  notes: string[];
  first_date: string;
  last_date: string;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, `ติดต่อ backend ไม่ได้ (${API_URL})`);
  }
  if (!res.ok) {
    if (res.status === 429) throw new ApiError(429, "มีการเรียกใช้ถี่เกินไป กรุณารอสักครู่แล้วลองใหม่");
    let msg = res.status === 401 ? "ต้องใช้รหัสผู้ดูแล" : res.statusText;
    try {
      const body = await res.json();
      msg = body.error ?? body.detail ?? body.title ?? msg;
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export interface AppConfig {
  /** precomputed = free hosting: forecasts come from the daily batch job, no admin jobs on the site */
  mode: "live" | "precomputed";
  maxHorizon: number;
}

export const api = {
  config: () => request<AppConfig>(`/api/config`),
  symbols: () => request<SymbolInfo[]>(`/api/symbols`),
  overview: () => request<Overview[]>(`/api/overview`),
  prices: (symbol: string) => request<Price[]>(`/api/stocks/${symbol}/prices`),
  summary: (symbol: string) => request<Summary>(`/api/stocks/${symbol}/summary`),
  metrics: (symbol: string) => request<ModelMetric[]>(`/api/models/${symbol}/metrics`),
  latestForecast: (symbol: string) => request<Forecast>(`/api/forecasts/symbol/${symbol}/latest`),
  createForecast: (symbol: string, model: string, horizon: number) =>
    request<Forecast>(`/api/forecasts`, { method: "POST", body: JSON.stringify({ symbol, model, horizon }) }),
  /** Resolves when the key is accepted (or no key is required); rejects with 401 otherwise. */
  adminCheck: (adminKey: string) =>
    request<{ ok: boolean; protectedByKey: boolean }>(`/api/admin/check`, { headers: { "X-Admin-Key": adminKey } }),
  /** symbol = null ingests every tracked stock */
  ingest: (symbol: string | null, adminKey: string, dataset?: string) =>
    request<{ results: IngestResult[]; errors: { symbol: string; error: string }[] }>(`/api/admin/ingest`, {
      method: "POST",
      headers: { "X-Admin-Key": adminKey },
      body: JSON.stringify({ symbol, dataset: dataset || null }),
    }),
  /** symbol = null trains every tracked stock */
  train: (symbol: string | null, adminKey: string) =>
    request<{ results: Record<string, unknown[]>; errors: { symbol: string; error: string }[] }>(
      `/api/admin/train`,
      { method: "POST", headers: { "X-Admin-Key": adminKey }, body: JSON.stringify({ symbol }) },
    ),
};

export const MODEL_LABELS: Record<string, string> = {
  auto: "เลือกอัตโนมัติ",
  naive_drift: "Random Walk + Drift",
  holt_damped: "Holt Damped Trend",
  ridge_ar: "Ridge Autoregression",
  gbm: "Gradient Boosting",
};
