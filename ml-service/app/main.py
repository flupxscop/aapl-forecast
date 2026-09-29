"""FastAPI model service. Called by the .NET backend, not by the browser."""
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import config, db, pipeline, symbols
from .forecasting import MODEL_FACTORIES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ml")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        db.sync_symbols(symbols.SYMBOLS)
        log.info("Synced %d symbols to the database", len(symbols.SYMBOLS))
    except Exception:  # DB may still be starting; /symbols/sync can be called later
        log.exception("Could not sync symbols at startup")
    yield


app = FastAPI(title="Stock Forecast - ML service", version="2.0.0", lifespan=lifespan)


class IngestRequest(BaseModel):
    symbol: str | None = Field(None, description="Symbol to ingest; empty = all symbols")
    dataset: str | None = Field(None, description="Override source: Kaggle slug, kaggle.com URL or direct CSV link")
    download: bool = True


class TrainRequest(BaseModel):
    symbol: str | None = Field(None, description="Symbol to train; empty = all symbols")
    models: list[str] | None = None


class ForecastRequest(BaseModel):
    symbol: str = config.SYMBOL
    model: str = "auto"
    horizon: int = Field(30, ge=1, le=365)


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # e.g. missing Kaggle credentials, DB down
        log.exception("Request failed")
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:500]}")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/models")
def models():
    return {"models": ["auto", *MODEL_FACTORIES]}


@app.get("/symbols")
def list_symbols():
    return {"symbols": [asdict(s) for s in symbols.SYMBOLS.values()]}


@app.post("/symbols/sync")
def sync_symbols():
    _run(db.sync_symbols, symbols.SYMBOLS)
    return {"synced": len(symbols.SYMBOLS)}


@app.post("/ingest")
def ingest(req: IngestRequest):
    if not req.symbol and req.dataset:
        raise HTTPException(400, "ระบุ dataset เองได้เฉพาะตอนนำเข้าทีละหุ้น")
    _run(db.sync_symbols, symbols.SYMBOLS)
    return _run(pipeline.ingest, symbol=req.symbol, dataset=req.dataset or None, download=req.download)


@app.post("/train")
def train(req: TrainRequest):
    out = _run(pipeline.train, symbol=req.symbol, models=req.models)
    return {
        "results": {
            s: [{k: (str(v) if k in ("train_start", "train_end") else v) for k, v in r.items()} for r in runs]
            for s, runs in out["results"].items()
        },
        "errors": out["errors"],
    }


@app.post("/forecast")
def forecast(req: ForecastRequest):
    return _run(pipeline.forecast, symbol=req.symbol, model_name=req.model, horizon=req.horizon)
