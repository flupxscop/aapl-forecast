"""Thin PostgreSQL access layer (psycopg 3)."""
from __future__ import annotations

import json
from contextlib import contextmanager

import numpy as np
import pandas as pd
import psycopg

from . import config


@contextmanager
def connect():
    with psycopg.connect(config.DATABASE_URL) as conn:
        yield conn


def _clean(v):
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return float(v)
    return v


def _price_rows(df: pd.DataFrame, symbol: str, source: str) -> list[tuple]:
    return [
        (symbol, r.trade_date, _clean(r.open), _clean(r.high), _clean(r.low), _clean(r.close),
         _clean(r.adj_close), None if _clean(r.volume) is None else int(round(float(r.volume))), source)
        for r in df.itertuples(index=False)
    ]


_UPSERT_SQL = """
        INSERT INTO stock_prices (symbol, trade_date, open, high, low, close, adj_close, volume, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol, trade_date) DO UPDATE SET
            open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close,
            adj_close = EXCLUDED.adj_close, volume = EXCLUDED.volume, source = EXCLUDED.source
"""


def upsert_prices(df: pd.DataFrame, symbol: str, source: str) -> int:
    rows = _price_rows(df, symbol, source)
    with connect() as conn, conn.cursor() as cur:
        cur.executemany(_UPSERT_SQL, rows)
    return len(rows)


def replace_prices(df: pd.DataFrame, symbol: str, source: str) -> int:
    """Full refresh of one symbol's history in a single transaction."""
    rows = _price_rows(df, symbol, source)
    with connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM stock_prices WHERE symbol = %s", (symbol,))
        cur.executemany(_UPSERT_SQL, rows)
    return len(rows)


SYMBOLS_DDL = """
CREATE TABLE IF NOT EXISTS symbols (
    symbol          VARCHAR(16)  PRIMARY KEY,
    name            VARCHAR(128) NOT NULL,
    display_ticker  VARCHAR(32)  NOT NULL,
    exchange        VARCHAR(32)  NOT NULL,
    currency        VARCHAR(8)   NOT NULL DEFAULT 'USD',
    native_currency VARCHAR(8)   NOT NULL DEFAULT 'USD',
    kaggle_dataset  VARCHAR(256),
    yahoo_ticker    VARCHAR(32),
    sort_order      INT          NOT NULL DEFAULT 0
)
"""


def sync_symbols(registry) -> None:
    """Create the symbols table if needed (older databases) and upsert the registry."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(SYMBOLS_DDL)
        for s in registry.values():
            cur.execute(
                """INSERT INTO symbols (symbol, name, display_ticker, exchange, currency, native_currency,
                                        kaggle_dataset, yahoo_ticker, sort_order)
                   VALUES (%s,%s,%s,%s,'USD',%s,%s,%s,%s)
                   ON CONFLICT (symbol) DO UPDATE SET
                     name = EXCLUDED.name, display_ticker = EXCLUDED.display_ticker, exchange = EXCLUDED.exchange,
                     native_currency = EXCLUDED.native_currency, kaggle_dataset = EXCLUDED.kaggle_dataset,
                     yahoo_ticker = EXCLUDED.yahoo_ticker, sort_order = EXCLUDED.sort_order""",
                (s.symbol, s.name, s.display_ticker, s.exchange, s.native_currency, s.kaggle,
                 s.yahoo, s.sort_order),
            )
        cur.execute("DELETE FROM symbols WHERE NOT (symbol = ANY(%s))", (list(registry),))


def load_series(symbol: str) -> pd.DataFrame:
    """Daily series used for modelling: adjusted close when available, else close."""
    sql = """
        SELECT trade_date, COALESCE(adj_close, close) AS price
        FROM stock_prices WHERE symbol = %s ORDER BY trade_date
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (symbol,))
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=["trade_date", "price"])


def save_model_runs(symbol: str, runs: list[dict]) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE model_runs SET is_best = FALSE WHERE symbol = %s", (symbol,))
        for r in runs:
            cur.execute(
                """INSERT INTO model_runs (symbol, model_name, train_start, train_end, test_days,
                       mae, rmse, mape, direction_acc, is_best, params)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (symbol, r["model_name"], r["train_start"], r["train_end"], r["test_days"],
                 r["mae"], r["rmse"], r["mape"], r["direction_acc"], r["is_best"],
                 json.dumps(r["params"])),
            )


def run_sql_file(path: str) -> None:
    """Execute an idempotent SQL script (used to create the schema on a fresh hosted database)."""
    with open(path, encoding="utf-8") as f:
        sql = f.read()
    with connect() as conn:
        conn.execute(sql)


def save_forecast(fc: dict) -> int:
    """Store a forecast produced by pipeline.forecast_from_series; returns its id."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO forecasts (symbol, model_name, horizon, base_date, base_close)
               VALUES (%s,%s,%s,%s,%s) RETURNING id""",
            (fc["symbol"], fc["model"], fc["horizon"], fc["base_date"], fc["base_close"]),
        )
        fid = cur.fetchone()[0]
        cur.executemany(
            """INSERT INTO forecast_points (forecast_id, step, target_date, predicted, lower, upper)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            [(fid, p["step"], p["date"], p["predicted"], p["lower"], p["upper"]) for p in fc["points"]],
        )
    return fid


def cleanup(keep_forecast_days: int = 120, keep_run_days: int = 180) -> tuple[int, int]:
    """Keep the hosted database small (free tiers have ~0.5 GB)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM forecasts WHERE created_at < now() - make_interval(days => %s)", (keep_forecast_days,))
        f = cur.rowcount
        cur.execute("DELETE FROM model_runs WHERE trained_at < now() - make_interval(days => %s) AND NOT is_best",
                    (keep_run_days,))
        r = cur.rowcount
    return f, r
