"""Registry of the stocks the platform tracks.

Add a stock by adding one entry here - ingest, training, the API and the web UI
pick it up automatically (restart the ml service so it is written to the DB).

    kaggle   : Kaggle dataset used as the historical base (None = Yahoo only)
    yahoo    : Yahoo Finance ticker used to top the data up to the latest trading day
    fx       : Yahoo FX ticker (units of local currency per 1 USD) to convert prices to USD
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class SymbolInfo:
    symbol: str
    name: str
    display_ticker: str
    exchange: str
    yahoo: str
    kaggle: str | None = None
    native_currency: str = "USD"
    fx: str | None = None
    sort_order: int = 0


SYMBOLS: dict[str, SymbolInfo] = {s.symbol: s for s in [
    SymbolInfo("AAPL", "Apple", "AAPL", "NASDAQ", "AAPL",
               kaggle="guillemservera/aapl-stock-data", sort_order=1),
    SymbolInfo("NVDA", "NVIDIA", "NVDA", "NASDAQ", "NVDA",
               kaggle="kalilurrahman/nvidia-stock-data-latest-and-updated", sort_order=2),
    SymbolInfo("SAMSUNG", "Samsung Electronics", "005930.KS", "KRX", "005930.KS",
               kaggle="caesarmario/samsung-electronics-stock-historical-price",
               native_currency="KRW", fx="KRW=X", sort_order=3),
    SymbolInfo("META", "Meta Platforms", "META", "NASDAQ", "META",
               kaggle="varpit94/facebook-stock-data", sort_order=4),
    # IPO on 12 Jun 2026 - too new for Kaggle, so Yahoo only (short history)
    SymbolInfo("SPCX", "SpaceX", "SPCX", "NASDAQ", "SPCX", kaggle=None, sort_order=5),
]}


def get(symbol: str) -> SymbolInfo:
    key = symbol.strip().upper()
    if key not in SYMBOLS:
        raise ValueError(f"Unknown symbol '{symbol}'. Supported: {', '.join(SYMBOLS)}")
    return SYMBOLS[key]
