"""Offline tests: no database or Kaggle access needed.   Run:  pytest -q"""
import numpy as np
import pandas as pd
import pytest

from app import config, data_loader, pipeline
from app.forecasting import MODEL_FACTORIES, backtest


def synthetic_prices(n=1500, seed=0):
    rng = np.random.default_rng(seed)
    y = np.log(20) + np.cumsum(0.0006 + 0.018 * rng.standard_normal(n))
    dates = pd.bdate_range("2019-01-02", periods=n)
    return pd.DataFrame({"trade_date": dates.date, "price": np.exp(y)})


@pytest.mark.parametrize("name", list(MODEL_FACTORIES))
def test_models_backtest_and_forecast(name):
    y = np.log(synthetic_prices()["price"].to_numpy())
    m = backtest(MODEL_FACTORIES[name](), y, test_days=40, horizon=5)
    assert m["mape"] < 15 and 0 <= m["direction_acc"] <= 100
    mean, std = MODEL_FACTORIES[name]().fit(y).forecast(y, 10)
    assert mean.shape == (10,) and np.all(std > 0) and np.all(np.diff(std) > 0)


def test_train_and_forecast_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODEL_DIR", str(tmp_path))
    s = synthetic_prices()
    runs = pipeline.train_on_series(s, "TEST", test_days=30, horizon=3)
    assert sum(r["is_best"] for r in runs) == 1
    fc = pipeline.forecast_from_series(s, "TEST", "auto", 15)
    assert len(fc["points"]) == 15
    for p in fc["points"]:
        assert p["lower"] < p["predicted"] < p["upper"]
    assert fc["points"][0]["date"] > fc["base_date"]


def test_normalise_various_csv_layouts():
    a = pd.DataFrame({"Date": ["2024-01-03", "2024-01-02"], "Open": [1, 2], "High": [1, 2], "Low": [1, 2],
                      "Close": [10.5, 11.0], "Adj Close": [10.4, 10.9], "Volume": [100, 200]})
    out = data_loader.normalise_prices(a)
    assert list(out.columns) == ["trade_date", "open", "high", "low", "close", "adj_close", "volume"]
    assert str(out.trade_date.iloc[0]) == "2024-01-02"

    b = pd.DataFrame({"date": ["01/02/2024"], "Close/Last": ["$185.64"], "Volume": ["82,488,700"],
                      "Ticker": ["AAPL"]})
    out = data_loader.normalise_prices(b)
    assert out.close.iloc[0] == pytest.approx(185.64) and out.volume.iloc[0] == 82488700


def test_resolve_source_variants():
    assert data_loader.resolve_source("owner/some-data") == ("kaggle", "owner/some-data")
    assert data_loader.resolve_source("https://www.kaggle.com/datasets/owner/some-data/data") == ("kaggle", "owner/some-data")
    long_url = "https://storage.googleapis.com/kagglesdsdata/datasets/1/2/aapl_raw_data.csv?X-Goog-Signature=" + "a" * 600
    kind, value = data_loader.resolve_source(long_url)
    assert kind == "url" and len(data_loader.source_folder(kind, value)) < 40
    with pytest.raises(ValueError):
        data_loader.resolve_source("not a dataset")


# ---------------------------------------------------------------- multi-symbol data pipeline
def _ohlc(dates, close, adj=None, volume=1000.0):
    close = np.asarray(close, dtype=float)
    return pd.DataFrame({"trade_date": [d.date() for d in dates], "open": close, "high": close * 1.01,
                         "low": close * 0.99, "close": close,
                         "adj_close": close if adj is None else adj, "volume": volume})


def test_stitch_rescales_after_split():
    d = pd.bdate_range("2024-01-01", periods=100)
    kaggle = _ohlc(d[:80], np.full(80, 1000.0))          # pre-split prices
    yahoo = _ohlc(d[60:], np.full(40, 100.0))            # 10:1 split-adjusted
    out, scale = data_loader.stitch(kaggle, yahoo)
    assert scale == pytest.approx(0.1)
    assert len(out) == 100 and out.trade_date.is_monotonic_increasing
    assert np.allclose(out.close, 100.0)


def test_convert_to_usd():
    d = pd.bdate_range("2024-01-01", periods=5)
    krw = _ohlc(d, [70000, 71000, 72000, 73000, 74000])
    fx = _ohlc(d[1:], [1400.0] * 4)                       # first day has no FX rate -> dropped
    out = data_loader.convert_to_usd(krw, fx)
    assert len(out) == 4 and out.close.iloc[0] == pytest.approx(71000 / 1400)


def test_short_history_uses_simple_models(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODEL_DIR", str(tmp_path))
    s = synthetic_prices(n=75)                            # ~3.5 months, like a fresh IPO
    runs = pipeline.train_on_series(s, "SPCX")
    assert {r["model_name"] for r in runs} <= {"naive_drift", "holt_damped"}
    assert runs[0]["test_days"] == 15
    fc = pipeline.forecast_from_series(s, "SPCX", "auto", 10)
    assert len(fc["points"]) == 10
    with pytest.raises(FileNotFoundError):
        pipeline.forecast_from_series(s, "SPCX", "gbm", 10)


def test_ingest_symbol_kaggle_plus_yahoo_with_fx(monkeypatch):
    from app import db
    d = pd.bdate_range("2020-01-01", periods=300)
    stored = {}
    monkeypatch.setattr(pipeline, "_load_base",
                        lambda info, ds, dl: (_ohlc(d[:250], np.linspace(50000, 60000, 250)), "kaggle:x/y"))

    def fake_yahoo(ticker, start=None):
        if ticker == "KRW=X":
            return _ohlc(d, np.full(300, 1250.0))
        return _ohlc(d[200:], np.linspace(58000, 65000, 100))

    monkeypatch.setattr(data_loader, "fetch_yahoo", fake_yahoo)
    monkeypatch.setattr(db, "replace_prices", lambda df, sym, source: stored.update(df=df, sym=sym, src=source) or len(df))
    r = pipeline.ingest_symbol("samsung")
    assert r["symbol"] == "SAMSUNG" and r["rows"] == 300
    assert stored["src"] == "kaggle:x/y+yahoo:005930.KS"
    assert stored["df"].close.iloc[-1] == pytest.approx(65000 / 1250)


def test_ingest_falls_back_to_yahoo_when_kaggle_fails(monkeypatch):
    from app import db
    d = pd.bdate_range("2024-01-01", periods=120)

    def broken(*a):
        raise OSError("no kaggle.json")

    monkeypatch.setattr(pipeline, "_load_base", broken)
    monkeypatch.setattr(data_loader, "fetch_yahoo", lambda t, start=None: _ohlc(d, np.linspace(100, 120, 120)))
    monkeypatch.setattr(db, "replace_prices", lambda df, sym, source: len(df))
    r = pipeline.ingest_symbol("NVDA")
    assert r["rows"] == 120 and r["sources"] == ["yahoo:NVDA"] and r["notes"]
