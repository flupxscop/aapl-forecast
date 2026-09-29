"""Ingest -> train -> forecast pipeline used by the API and the CLI scripts."""
from __future__ import annotations

import json
import logging
import os
from datetime import date

import joblib
import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

from . import config, data_loader, db, symbols
from .forecasting import MODEL_FACTORIES, backtest, to_price_forecast

log = logging.getLogger(__name__)
_US_TRADING_DAY = CustomBusinessDay(calendar=USFederalHolidayCalendar())
_LONG_MODELS_MIN_ROWS = 400  # lag-feature ML models need a few hundred days of history


# ----------------------------------------------------------------------------- ingest
_EMPTY = pd.DataFrame(columns=["trade_date", *data_loader.PRICE_COLS, "volume"])


def _load_base(info: symbols.SymbolInfo, dataset: str | None, download: bool) -> tuple[pd.DataFrame, str]:
    """Historical base from Kaggle (or a direct CSV link)."""
    kind, value = data_loader.resolve_source(dataset or info.kaggle)
    folder = os.path.join(config.DATA_DIR, data_loader.source_folder(kind, value))
    if download or not os.path.isdir(folder):
        if kind == "kaggle":
            data_loader.download_kaggle_dataset(value, folder)
        else:
            data_loader.download_url(value, folder)
    hints = [info.symbol, info.name.split()[0], info.yahoo.split(".")[0], info.display_ticker]
    csv_path = data_loader.find_csv(folder, hints)
    df = data_loader.load_csv(csv_path, [info.symbol, info.yahoo, info.display_ticker])
    # never store signed download URLs (they contain credentials) - keep the path only
    label = f"kaggle:{value}" if kind == "kaggle" else "url:" + value.split("?")[0][-60:]
    return df, label


def ingest_symbol(symbol: str, dataset: str | None = None, csv_path: str | None = None,
                  download: bool = True) -> dict:
    """Kaggle history + Yahoo Finance top-up (+ FX conversion to USD) -> stock_prices."""
    info = symbols.get(symbol)
    notes, sources = [], []

    base = _EMPTY
    if csv_path:
        base = data_loader.load_csv(csv_path, [info.symbol, info.yahoo])
        sources.append("csv:" + os.path.basename(csv_path))
    elif dataset or info.kaggle:
        try:
            base, label = _load_base(info, dataset, download)
            sources.append(label)
        except Exception as e:
            if dataset:  # the user asked for this source explicitly - surface the error
                raise
            notes.append(f"Kaggle ใช้ไม่ได้ ({type(e).__name__}: {str(e)[:150]}) - ใช้ Yahoo Finance แทน")

    recent = _EMPTY
    try:
        start = None if base.empty else str(pd.Timestamp(base.trade_date.max()) - pd.Timedelta(days=90))[:10]
        recent = data_loader.fetch_yahoo(info.yahoo, start)
        sources.append(f"yahoo:{info.yahoo}")
    except Exception as e:
        if base.empty:
            raise ValueError(f"โหลดข้อมูล {symbol} ไม่ได้ทั้งจาก Kaggle และ Yahoo Finance: {e}")
        notes.append(f"Yahoo Finance ใช้ไม่ได้ ({type(e).__name__}) - ใช้ข้อมูล Kaggle อย่างเดียว")

    df, scale = data_loader.stitch(base, recent)
    if abs(scale - 1) > 0.01:
        notes.append(f"ปรับสเกลข้อมูล Kaggle x{scale:.4g} ให้ต่อกับ Yahoo (เช่น มีการแตกพาร์หลังวันที่ทำ dataset)")
    if info.fx:
        fx = data_loader.fetch_yahoo(info.fx, str(df.trade_date.min()))
        before = len(df)
        df = data_loader.convert_to_usd(df, fx)
        notes.append(f"แปลงราคาจาก {info.native_currency} เป็น USD ด้วยอัตรา {info.fx} รายวัน"
                     + (f" (ตัด {before - len(df)} วันที่ไม่มีอัตราแลกเปลี่ยน)" if before > len(df) else ""))
    if df.empty:
        raise ValueError(f"ไม่พบข้อมูลราคาที่ใช้ได้สำหรับ {symbol}")

    n = db.replace_prices(df, info.symbol, source="+".join(sources)[:128])
    return {"symbol": info.symbol, "rows": n, "sources": sources, "notes": notes,
            "first_date": str(df.trade_date.iloc[0]), "last_date": str(df.trade_date.iloc[-1])}


def ingest(symbol: str | None = None, dataset: str | None = None, csv_path: str | None = None,
           download: bool = True) -> dict:
    """Ingest one symbol, or every registered symbol when `symbol` is None."""
    if symbol:
        return {"results": [ingest_symbol(symbol, dataset, csv_path, download)], "errors": []}
    results, errors = [], []
    for s in symbols.SYMBOLS:
        try:
            results.append(ingest_symbol(s, download=download))
        except Exception as e:
            log.exception("Ingest failed for %s", s)
            errors.append({"symbol": s, "error": f"{type(e).__name__}: {e}"})
    return {"results": results, "errors": errors}


# ----------------------------------------------------------------------------- train
def _model_path(symbol: str, name: str) -> str:
    return os.path.join(config.MODEL_DIR, f"{symbol}_{name}.joblib")


def _meta_path(symbol: str) -> str:
    return os.path.join(config.MODEL_DIR, f"{symbol}_meta.json")


def train_on_series(series: pd.DataFrame, symbol: str, models: list[str] | None = None,
                    test_days: int = config.TEST_DAYS, horizon: int = config.EVAL_HORIZON) -> list[dict]:
    """Back-test every model, then refit it on the full history and save it.

    Short histories (e.g. a recent IPO) get a smaller test window and only the
    models that can work with little data (naive drift, Holt)."""
    n = len(series)
    if n < 40:
        raise ValueError(f"{symbol}: ต้องมีข้อมูลอย่างน้อย 40 วันทำการ (มี {n} วัน)")
    test_days = min(test_days, max(10, n // 5))
    candidates = models or list(MODEL_FACTORIES)
    if n < _LONG_MODELS_MIN_ROWS + test_days:
        candidates = [m for m in candidates if m in ("naive_drift", "holt_damped")] or ["naive_drift"]
    unknown = [m for m in candidates if m not in MODEL_FACTORIES]
    if unknown:
        raise ValueError(f"Unknown model(s): {', '.join(unknown)}")
    y = np.log(series["price"].to_numpy(dtype=float))
    os.makedirs(config.MODEL_DIR, exist_ok=True)
    for f in os.listdir(config.MODEL_DIR):  # drop models from earlier runs that no longer apply
        if f.startswith(f"{symbol}_") and f.endswith(".joblib"):
            os.remove(os.path.join(config.MODEL_DIR, f))
    runs = []
    for name in candidates:
        log.info("Training %s", name)
        metrics = backtest(MODEL_FACTORIES[name](), y, test_days=test_days, horizon=horizon)
        final = MODEL_FACTORIES[name]().fit(y)
        joblib.dump(final, _model_path(symbol, name))
        runs.append({
            "model_name": name, **metrics, "params": final.params, "test_days": test_days,
            "train_start": series.trade_date.iloc[0], "train_end": series.trade_date.iloc[-1],
        })
    best = min(runs, key=lambda r: r["mape"])
    for r in runs:
        r["is_best"] = r is best
    with open(_meta_path(symbol), "w") as f:
        json.dump({"best_model": best["model_name"], "models": [r["model_name"] for r in runs],
                   "trained_at": str(date.today()), "rows": n}, f)
    return runs


def train_symbol(symbol: str, models: list[str] | None = None) -> list[dict]:
    symbol = symbols.get(symbol).symbol
    series = db.load_series(symbol)
    if series.empty:
        raise ValueError(f"ยังไม่มีข้อมูล {symbol} ในฐานข้อมูล - นำเข้าข้อมูลก่อน")
    runs = train_on_series(series, symbol, models)
    db.save_model_runs(symbol, runs)
    return runs


def train(symbol: str | None = None, models: list[str] | None = None) -> dict:
    """Train one symbol, or every registered symbol that has data when `symbol` is None."""
    targets = [symbol] if symbol else list(symbols.SYMBOLS)
    results, errors = {}, []
    for s in targets:
        try:
            results[s] = train_symbol(s, models)
        except Exception as e:
            if symbol:
                raise
            log.exception("Training failed for %s", s)
            errors.append({"symbol": s, "error": f"{type(e).__name__}: {e}"})
    return {"results": results, "errors": errors}


# ----------------------------------------------------------------------------- forecast
def best_model_name(symbol: str) -> str:
    try:
        with open(_meta_path(symbol)) as f:
            return json.load(f)["best_model"]
    except FileNotFoundError:
        raise FileNotFoundError(f"ยังไม่ได้เทรนโมเดลสำหรับ {symbol} - กด 'เทรนโมเดล' ก่อน")


def forecast_from_series(series: pd.DataFrame, symbol: str, model_name: str, horizon: int) -> dict:
    if model_name in (None, "", "auto"):
        model_name = best_model_name(symbol)
    if model_name not in MODEL_FACTORIES:
        raise ValueError(f"Unknown model '{model_name}'. Options: auto, {', '.join(MODEL_FACTORIES)}")
    path = _model_path(symbol, model_name)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"โมเดล {model_name} ยังไม่ได้เทรนสำหรับ {symbol} (หุ้นที่มีข้อมูลน้อยใช้ได้เฉพาะ naive_drift / holt_damped)")
    model = joblib.load(path)

    y = np.log(series["price"].to_numpy(dtype=float))
    mean, std = model.forecast(y, horizon)
    pred, lo, hi = to_price_forecast(mean, std)
    base_date = pd.Timestamp(series.trade_date.iloc[-1])
    info = symbols.SYMBOLS.get(symbol)
    day = _US_TRADING_DAY if info is None or info.exchange in ("NASDAQ", "NYSE") else pd.offsets.BDay()
    dates = pd.date_range(base_date + day, periods=horizon, freq=day)
    return {
        "symbol": symbol,
        "model": model_name,
        "horizon": horizon,
        "base_date": base_date.date().isoformat(),
        "base_close": float(series["price"].iloc[-1]),
        "points": [
            {"step": i + 1, "date": d.date().isoformat(), "predicted": round(float(p), 4),
             "lower": round(float(l), 4), "upper": round(float(u), 4)}
            for i, (d, p, l, u) in enumerate(zip(dates, pred, lo, hi))
        ],
    }


def forecast(symbol: str = config.SYMBOL, model_name: str = "auto", horizon: int = 30) -> dict:
    symbol = symbols.get(symbol).symbol
    return forecast_from_series(db.load_series(symbol), symbol, model_name, horizon)
