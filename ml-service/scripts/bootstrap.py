"""One-shot CLI: load prices (Kaggle + Yahoo Finance) into Postgres and train all models.

    python -m scripts.bootstrap                                  # every symbol in app/symbols.py
    python -m scripts.bootstrap --symbol NVDA
    python -m scripts.bootstrap --symbol AAPL --dataset owner/name
    python -m scripts.bootstrap --symbol AAPL --csv /path/AAPL.csv
"""
import argparse
import logging

from app import pipeline

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default=None, help="one symbol (default: all registered symbols)")
    p.add_argument("--dataset", default=None, help="override source for --symbol")
    p.add_argument("--csv", default=None, help="local CSV for --symbol (skips Kaggle)")
    p.add_argument("--skip-train", action="store_true")
    a = p.parse_args()
    if (a.dataset or a.csv) and not a.symbol:
        p.error("--dataset/--csv need --symbol")

    res = pipeline.ingest(symbol=a.symbol, dataset=a.dataset, csv_path=a.csv)
    for r in res["results"]:
        print(f"[ingest] {r['symbol']:8s} {r['rows']:6d} rows {r['first_date']} -> {r['last_date']}  "
              f"({' + '.join(r['sources'])})")
        for n in r["notes"]:
            print("          note:", n)
    for e in res["errors"]:
        print(f"[ingest] {e['symbol']:8s} FAILED: {e['error']}")

    if not a.skip_train:
        out = pipeline.train(symbol=a.symbol)
        for sym, runs in out["results"].items():
            for r in runs:
                flag = "  <- best" if r["is_best"] else ""
                print(f"[train]  {sym:8s} {r['model_name']:12s} MAPE={r['mape']:.2f}%  "
                      f"DirAcc={r['direction_acc']:.1f}%{flag}")
        for e in out["errors"]:
            print(f"[train]  {e['symbol']:8s} FAILED: {e['error']}")
