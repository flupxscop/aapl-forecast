"""Daily auto-update for the production stack (runs as the `scheduler` container).

Once a day at UPDATE_TIME_UTC it:
  1. asks the ML service to ingest fresh prices for every stock (Kaggle + Yahoo Finance)
  2. retrains and back-tests every model
  3. asks the .NET backend to create and store a new forecast for each stock

Uses only the standard library, and talks to the other services over HTTP so that only
the `ml` container ever touches model files.

Env: ML_URL, BACKEND_URL, UPDATE_TIME_UTC (HH:MM), FORECAST_HORIZON,
     RUN_ON_START = if-empty (default) | always | never
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

ML_URL = os.getenv("ML_URL", "http://ml:8000").rstrip("/")
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8080").rstrip("/")
UPDATE_TIME_UTC = os.getenv("UPDATE_TIME_UTC", "22:30")
HORIZON = int(os.getenv("FORECAST_HORIZON", "30"))
RUN_ON_START = os.getenv("RUN_ON_START", "if-empty").lower()

logging.basicConfig(level=logging.INFO, format="%(asctime)s scheduler %(levelname)s %(message)s")
log = logging.getLogger("scheduler")


def call(method: str, url: str, body: dict | None = None, timeout: float = 60) -> dict | list:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        raw = res.read()
    return json.loads(raw) if raw else {}


def wait_until_ready(max_wait: float = 600) -> None:
    deadline = time.monotonic() + max_wait
    for url in (f"{ML_URL}/health", f"{BACKEND_URL}/api/health"):
        while True:
            try:
                call("GET", url, timeout=5)
                break
            except Exception:
                if time.monotonic() > deadline:
                    raise RuntimeError(f"{url} is not reachable")
                time.sleep(5)
    log.info("ML service and backend are up")


def next_run(now: datetime, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return target if target > now else target + timedelta(days=1)


def needs_initial_run() -> bool:
    overview = call("GET", f"{BACKEND_URL}/api/overview")
    return any(o.get("rows", 0) == 0 or o.get("bestModel") is None for o in overview)


def update_all() -> None:
    started = time.monotonic()
    log.info("Ingesting prices for all stocks")
    ing = call("POST", f"{ML_URL}/ingest", {}, timeout=1800)
    for r in ing.get("results", []):
        log.info("  %s: %s rows up to %s", r["symbol"], r["rows"], r["last_date"])
    for e in ing.get("errors", []):
        log.warning("  %s ingest failed: %s", e["symbol"], e["error"])

    log.info("Training models")
    tr = call("POST", f"{ML_URL}/train", {}, timeout=3600)
    for e in tr.get("errors", []):
        log.warning("  %s training failed: %s", e["symbol"], e["error"])

    for symbol in tr.get("results", {}):
        try:
            fc = call("POST", f"{BACKEND_URL}/api/forecasts",
                      {"symbol": symbol, "model": "auto", "horizon": HORIZON}, timeout=120)
            last = fc["points"][-1]
            log.info("  %s forecast (%s): %.2f on %s", symbol, fc["model"], last["predicted"], last["date"])
        except Exception as e:  # keep going with the other stocks
            log.warning("  %s forecast failed: %s", symbol, e)
    log.info("Daily update finished in %.0fs", time.monotonic() - started)


def main() -> None:
    wait_until_ready()
    try:
        if RUN_ON_START == "always" or (RUN_ON_START == "if-empty" and needs_initial_run()):
            update_all()
    except Exception:
        log.exception("Initial update failed")

    while True:
        target = next_run(datetime.now(timezone.utc), UPDATE_TIME_UTC)
        log.info("Next update at %s UTC", target.strftime("%Y-%m-%d %H:%M"))
        time.sleep(max(1.0, (target - datetime.now(timezone.utc)).total_seconds()))
        try:
            update_all()
        except urllib.error.HTTPError as e:
            log.error("Update failed: HTTP %s %s", e.code, e.read()[:300])
        except Exception:
            log.exception("Update failed")


if __name__ == "__main__":
    main()
