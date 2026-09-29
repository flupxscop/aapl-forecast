"""Load daily prices from Kaggle / direct CSV links / Yahoo Finance into one standard OHLCV frame."""
from __future__ import annotations

import glob
import logging
import os
import re

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# accepted aliases (lower-cased, non-alphanumerics stripped) -> canonical column
_ALIASES = {
    "date": "trade_date", "datetime": "trade_date", "timestamp": "trade_date", "tradedate": "trade_date",
    "open": "open", "high": "high", "low": "low",
    "close": "close", "closelast": "close", "price": "close",
    "adjclose": "adj_close", "adjustedclose": "adj_close",
    "volume": "volume", "vol": "volume",
}


_SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_KAGGLE_URL_RE = re.compile(r"kaggle\.com/datasets/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")


def resolve_source(text: str) -> tuple[str, str]:
    """Classify what the user typed.

    Returns ("kaggle", "owner/name") for a slug or a kaggle.com/datasets/... page URL,
    or ("url", url) for a direct http(s) link to a CSV/ZIP file (e.g. a Kaggle download link).
    """
    text = (text or "").strip()
    m = _KAGGLE_URL_RE.search(text)
    if m:
        return "kaggle", f"{m.group(1)}/{m.group(2)}"
    if text.lower().startswith(("http://", "https://")):
        return "url", text
    if _SLUG_RE.match(text):
        return "kaggle", text
    raise ValueError(
        "Dataset ต้องเป็น Kaggle slug เช่น 'owner/dataset-name', ลิงก์หน้า kaggle.com/datasets/..., "
        "หรือลิงก์ตรงไปยังไฟล์ CSV/ZIP"
    )


def source_folder(kind: str, value: str) -> str:
    """Short, filesystem-safe folder name for a source (URLs can be thousands of chars)."""
    if kind == "kaggle":
        return "kaggle__" + value.replace("/", "__")
    import hashlib
    return "url__" + hashlib.sha1(value.encode()).hexdigest()[:16]


def download_url(url: str, dest: str) -> str:
    """Download a CSV (or ZIP of CSVs) from a direct link into `dest`."""
    import io
    import urllib.request
    import zipfile
    from urllib.parse import unquote, urlparse

    os.makedirs(dest, exist_ok=True)
    log.info("Downloading %s", urlparse(url).netloc + urlparse(url).path)
    req = urllib.request.Request(url, headers={"User-Agent": "aapl-forecast/1.0"})
    with urllib.request.urlopen(req, timeout=300) as res:
        data = res.read()
    if data[:2] == b"PK":  # zip archive
        zipfile.ZipFile(io.BytesIO(data)).extractall(dest)
    else:
        name = os.path.basename(unquote(urlparse(url).path)) or "data.csv"
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:100]
        if not name.lower().endswith(".csv"):
            name += ".csv"
        with open(os.path.join(dest, name), "wb") as f:
            f.write(data)
    return dest


def download_kaggle_dataset(dataset: str, dest: str) -> str:
    """Download + unzip a Kaggle dataset. Needs ~/.kaggle/kaggle.json or
    KAGGLE_USERNAME / KAGGLE_KEY environment variables."""
    # empty KAGGLE_* vars (from docker-compose defaults) would shadow ~/.kaggle/kaggle.json
    for var in ("KAGGLE_USERNAME", "KAGGLE_KEY"):
        if not os.environ.get(var):
            os.environ.pop(var, None)
    from kaggle.api.kaggle_api_extended import KaggleApi  # imported lazily: it authenticates on import

    os.makedirs(dest, exist_ok=True)
    api = KaggleApi()
    api.authenticate()
    log.info("Downloading Kaggle dataset %s -> %s", dataset, dest)
    api.dataset_download_files(dataset, path=dest, unzip=True, quiet=True)
    return dest


def find_csv(folder: str, hints: list[str] | str = "AAPL") -> str:
    """Pick the CSV most likely to hold daily prices (file name matching one of `hints`)."""
    files = glob.glob(os.path.join(folder, "**", "*.csv"), recursive=True)
    if not files:
        raise FileNotFoundError(f"No CSV files found in {folder}")
    hints = [h.lower() for h in ([hints] if isinstance(hints, str) else hints) if h]

    def score(path: str) -> tuple:
        name = os.path.basename(path).lower()
        return (any(h in name for h in hints), "daily" in name or "1d" in name, os.path.getsize(path))

    return sorted(files, key=score, reverse=True)[0]


def _to_number(s: pd.Series) -> pd.Series:
    if not pd.api.types.is_numeric_dtype(s):
        s = s.astype(str).str.replace(r"[$,\s]", "", regex=True)
    return pd.to_numeric(s, errors="coerce").astype(float)


PRICE_COLS = ("open", "high", "low", "close", "adj_close")


def normalise_prices(df: pd.DataFrame, symbol: str | list[str] = "AAPL") -> pd.DataFrame:
    """Map arbitrary column names to trade_date/open/high/low/close/adj_close/volume."""
    wanted = {s.upper() for s in ([symbol] if isinstance(symbol, str) else symbol)}
    # multi-ticker files: keep only the requested symbol
    for col in df.columns:
        if re.sub(r"[^a-z]", "", str(col).lower()) in ("ticker", "symbol", "name"):
            mask = df[col].astype(str).str.upper().isin(wanted)
            if mask.any():
                df = df[mask]
            break
    rename = {}
    for col in df.columns:
        key = re.sub(r"[^a-z0-9]", "", str(col).lower())
        if key in _ALIASES and _ALIASES[key] not in rename.values():
            rename[col] = _ALIASES[key]
    df = df.rename(columns=rename)
    if "trade_date" not in df or "close" not in df:
        raise ValueError(f"CSV needs a date and a close column, got {list(df.columns)}")

    out = pd.DataFrame({"trade_date": pd.to_datetime(df["trade_date"], errors="coerce", utc=True).dt.date})
    for col in (*PRICE_COLS, "volume"):
        out[col] = _to_number(df[col]) if col in df else np.nan
    out = out.dropna(subset=["trade_date", "close"])
    out = out[out["close"] > 0]
    out = out.drop_duplicates("trade_date", keep="last").sort_values("trade_date").reset_index(drop=True)
    return out


def load_csv(path: str, symbol: str | list[str] = "AAPL") -> pd.DataFrame:
    return normalise_prices(pd.read_csv(path), symbol)


# --------------------------------------------------------------------------- Yahoo Finance
def fetch_yahoo(ticker: str, start: str | None = None) -> pd.DataFrame:
    """Daily OHLCV from Yahoo Finance (Close is split-adjusted, Adj Close also dividend-adjusted)."""
    import yfinance as yf

    kwargs = {"start": start} if start else {"period": "max"}
    raw = yf.Ticker(ticker).history(interval="1d", auto_adjust=False, actions=False, **kwargs)
    if raw is None or raw.empty:
        raise ValueError(f"Yahoo Finance returned no data for {ticker}")
    raw = raw.reset_index()
    # keep the exchange-local calendar date (don't shift through UTC)
    raw["Date"] = pd.to_datetime(raw["Date"]).dt.tz_localize(None).dt.strftime("%Y-%m-%d")
    return normalise_prices(raw, ticker)


def stitch(base: pd.DataFrame, recent: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """Combine a historical base (Kaggle) with fresher data (Yahoo).

    Recent data wins on overlapping dates. If the two disagree in scale on the overlap
    (e.g. a stock split happened after the Kaggle file was made) the base is rescaled so
    the series is continuous. Returns (frame, scale_factor_applied_to_base)."""
    if base.empty:
        return recent.reset_index(drop=True), 1.0
    if recent.empty:
        return base.reset_index(drop=True), 1.0
    base, recent = base.copy(), recent.copy()
    overlap = base.merge(recent, on="trade_date", suffixes=("_b", "_r"))
    scale = 1.0
    if len(overlap) >= 3:
        scale = float((overlap["close_r"] / overlap["close_b"]).median())
        adj_scale = (overlap["adj_close_r"] / overlap["adj_close_b"]).median()
        adj_scale = float(adj_scale) if pd.notna(adj_scale) else scale
        if abs(scale - 1) > 0.01 or abs(adj_scale - 1) > 0.01:
            log.info("Rescaling base data: close x%.4f, adj_close x%.4f", scale, adj_scale)
            for c in ("open", "high", "low", "close"):
                base[c] = base[c] * scale
            base["adj_close"] = base["adj_close"] * adj_scale
            base["volume"] = base["volume"] / scale
    base = base[base["trade_date"] < recent["trade_date"].min()]
    out = pd.concat([base, recent], ignore_index=True)
    return out.sort_values("trade_date").reset_index(drop=True), scale


def convert_to_usd(df: pd.DataFrame, fx: pd.DataFrame) -> pd.DataFrame:
    """Divide local-currency prices by the daily FX rate (local units per 1 USD).
    Days before the FX history starts are dropped."""
    rate = fx.set_index("trade_date")["close"].rename("rate")
    out = df.merge(rate, left_on="trade_date", right_index=True, how="left")
    out["rate"] = out["rate"].ffill()
    out = out.dropna(subset=["rate"])
    for c in PRICE_COLS:
        out[c] = out[c] / out["rate"]
    return out.drop(columns="rate").reset_index(drop=True)
