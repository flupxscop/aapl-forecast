"""Batch pipeline for the free hosting setup (runs daily in GitHub Actions).

    python -m scripts.publish_forecasts

1. creates the schema if the database is new (db/init/01_schema.sql, idempotent)
2. ingests every stock (Kaggle history + Yahoo Finance top-up)
3. trains / back-tests every model and records the results
4. stores a MAX_HORIZON-day forecast for every trained model of every stock

The .NET API then serves these stored forecasts ("precomputed" mode): a shorter horizon is simply
the first N days of the stored path, because every model forecasts step by step.
Nothing needs to run in Python while people use the website.
"""
import logging
import os
import sys

from app import db, pipeline, symbols

MAX_HORIZON = int(os.getenv("MAX_HORIZON", "90"))
SCHEMA = os.getenv("SCHEMA_SQL", os.path.join(os.path.dirname(__file__), "..", "..", "db", "init", "01_schema.sql"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("publish")


def main() -> int:
    log.info("Ensuring schema from %s", SCHEMA)
    db.run_sql_file(SCHEMA)
    db.sync_symbols(symbols.SYMBOLS)

    ing = pipeline.ingest(symbol=None)
    for r in ing["results"]:
        log.info("ingest %-8s %6d rows -> %s (%s)", r["symbol"], r["rows"], r["last_date"], " + ".join(r["sources"]))
        for n in r["notes"]:
            log.info("         note: %s", n)
    for e in ing["errors"]:
        log.warning("ingest %-8s FAILED: %s", e["symbol"], e["error"])

    tr = pipeline.train(symbol=None)
    for e in tr["errors"]:
        log.warning("train  %-8s FAILED: %s", e["symbol"], e["error"])

    stored = 0
    for sym, runs in tr["results"].items():
        series = db.load_series(sym)
        for run in runs:
            fc = pipeline.forecast_from_series(series, sym, run["model_name"], MAX_HORIZON)
            db.save_forecast(fc)
            stored += 1
            flag = " (best)" if run["is_best"] else ""
            log.info("forecast %-8s %-12s MAPE %.2f%% -> %.2f on %s%s", sym, run["model_name"], run["mape"],
                     fc["points"][-1]["predicted"], fc["points"][-1]["date"], flag)

    deleted = db.cleanup()
    log.info("Stored %d forecasts; cleaned up %d old forecasts and %d old model runs", stored, *deleted)
    # fail the workflow (so GitHub emails you) only if nothing at all could be produced
    return 0 if stored else 1


if __name__ == "__main__":
    sys.exit(main())
