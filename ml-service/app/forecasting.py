"""Time-series forecasting models for daily stock prices.

All models work on the *log* of the (adjusted) close price. Working in log space
makes multiplicative moves additive and keeps forecasts strictly positive.

Every model implements the same tiny interface:

    fit(log_prices)                 -> self
    forecast(log_prices, horizon)   -> (mean_log_path, std_log_path)

`forecast` receives the full history to forecast from, so the same fitted model
can be evaluated at many forecast origins during back-testing without refitting.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

Z95 = 1.959964


# --------------------------------------------------------------------------- #
# Baseline: random walk with drift
# --------------------------------------------------------------------------- #
class NaiveDrift:
    """Random walk with drift. Hard to beat for stock prices - the benchmark."""

    name = "naive_drift"

    def __init__(self, window: int = 252):
        self.window = window
        self.params: dict = {"window": window}

    def fit(self, y: np.ndarray) -> "NaiveDrift":
        return self

    def forecast(self, y: np.ndarray, h: int):
        r = np.diff(y[-(self.window + 1):])
        mu, sigma = float(r.mean()), float(r.std(ddof=1))
        steps = np.arange(1, h + 1)
        return y[-1] + mu * steps, sigma * np.sqrt(steps)


# --------------------------------------------------------------------------- #
# Holt's damped-trend exponential smoothing (implemented in numpy)
# --------------------------------------------------------------------------- #
class HoltDamped:
    name = "holt_damped"

    def __init__(self, fit_window: int = 756):
        self.fit_window = fit_window
        self.alpha = self.beta = self.phi = None
        self.sigma = None
        self.params: dict = {}

    @staticmethod
    def _filter(y, alpha, beta, phi):
        level, trend = y[0], y[1] - y[0]
        sse, errors = 0.0, []
        for t in range(1, len(y)):
            pred = level + phi * trend
            err = y[t] - pred
            errors.append(err)
            sse += err * err
            new_level = pred + alpha * err
            trend = beta * (new_level - level) + (1 - beta) * phi * trend
            level = new_level
        return level, trend, sse, np.asarray(errors)

    def fit(self, y: np.ndarray) -> "HoltDamped":
        yy = y[-self.fit_window:]
        best = None
        for alpha in (0.6, 0.8, 0.9, 0.95, 0.99):
            for beta in (0.0, 0.01, 0.05, 0.1):
                for phi in (0.8, 0.9, 0.95, 0.98):
                    _, _, sse, _ = self._filter(yy, alpha, beta, phi)
                    if best is None or sse < best[0]:
                        best = (sse, alpha, beta, phi)
        _, self.alpha, self.beta, self.phi = best
        _, _, _, errs = self._filter(yy, self.alpha, self.beta, self.phi)
        self.sigma = float(np.std(errs[1:], ddof=1))
        self.params = {"alpha": self.alpha, "beta": self.beta, "phi": self.phi}
        return self

    def forecast(self, y: np.ndarray, h: int):
        level, trend, _, _ = self._filter(y[-self.fit_window:], self.alpha, self.beta, self.phi)
        steps = np.arange(1, h + 1)
        damp = np.cumsum(self.phi ** steps)
        return level + damp * trend, self.sigma * np.sqrt(steps)


# --------------------------------------------------------------------------- #
# Machine-learning models on lagged log returns (recursive multi-step)
# --------------------------------------------------------------------------- #
def _features_from_returns(r: np.ndarray, n_lags: int) -> np.ndarray:
    """Feature vector for predicting the next return from the return history r."""
    last = r[-n_lags:][::-1]  # most recent first
    return np.concatenate([
        last,
        [r[-5:].mean(), r[-20:].mean(), r[-60:].mean(),
         r[-20:].std(), r[-60:].std()],
    ])


@dataclass
class _ReturnRegressor:
    name: str
    make_estimator: Callable
    n_lags: int = 20
    train_window: int = 2520  # ~10 trading years
    estimator: object = None
    sigma: float | None = None
    params: dict = field(default_factory=dict)

    def _dataset(self, y: np.ndarray):
        r = np.diff(y)
        start = max(60, self.n_lags)
        X = np.array([_features_from_returns(r[:t], self.n_lags) for t in range(start, len(r))])
        return X, r[start:]

    def fit(self, y: np.ndarray):
        X, target = self._dataset(y[-(self.train_window + 1):])
        self.estimator = self.make_estimator().fit(X, target)
        resid = target - self.estimator.predict(X)
        self.sigma = float(np.std(resid, ddof=1))
        self.params = {"n_lags": self.n_lags, "train_window": self.train_window}
        return self

    def forecast(self, y: np.ndarray, h: int):
        r = list(np.diff(y[-200:]))
        path, level = [], y[-1]
        for _ in range(h):
            nxt = float(self.estimator.predict(_features_from_returns(np.asarray(r), self.n_lags)[None, :])[0])
            r.append(nxt)
            level += nxt
            path.append(level)
        steps = np.arange(1, h + 1)
        return np.asarray(path), self.sigma * np.sqrt(steps)


# module-level factories (not lambdas) so fitted models can be pickled with joblib
def _make_ridge():
    return make_pipeline(StandardScaler(), Ridge(alpha=10.0))


def _make_gbm():
    return HistGradientBoostingRegressor(
        max_iter=200, learning_rate=0.05, max_depth=3, l2_regularization=1.0, random_state=42
    )


def RidgeAR() -> _ReturnRegressor:
    return _ReturnRegressor("ridge_ar", _make_ridge)


def GradientBoosting() -> _ReturnRegressor:
    return _ReturnRegressor("gbm", _make_gbm)


MODEL_FACTORIES: dict[str, Callable] = {
    "naive_drift": NaiveDrift,
    "holt_damped": HoltDamped,
    "ridge_ar": RidgeAR,
    "gbm": GradientBoosting,
}


# --------------------------------------------------------------------------- #
# Back-testing
# --------------------------------------------------------------------------- #
def backtest(model, y: np.ndarray, test_days: int = 60, horizon: int = 5) -> dict:
    """Fit on everything before the test window, then forecast `horizon` steps
    ahead from every origin inside the window. Metrics are in price space."""
    split = len(y) - test_days
    model.fit(y[:split])
    abs_err, sq_err, pct_err, dir_hits, n_dir = [], [], [], 0, 0
    for origin in range(split, len(y) - 1):
        h = min(horizon, len(y) - 1 - origin)
        mean, _ = model.forecast(y[: origin + 1], h)
        actual = np.exp(y[origin + 1: origin + 1 + h])
        pred = np.exp(mean)
        abs_err.extend(np.abs(pred - actual))
        sq_err.extend((pred - actual) ** 2)
        pct_err.extend(np.abs(pred - actual) / actual)
        # did the model get the direction of the next day's move right?
        dir_hits += int(np.sign(mean[0] - y[origin]) == np.sign(y[origin + 1] - y[origin]))
        n_dir += 1
    return {
        "mae": float(np.mean(abs_err)),
        "rmse": float(np.sqrt(np.mean(sq_err))),
        "mape": float(np.mean(pct_err) * 100),
        "direction_acc": float(dir_hits / max(n_dir, 1) * 100),
    }


def to_price_forecast(mean_log: np.ndarray, std_log: np.ndarray):
    """Convert log-space forecast into price with a 95% interval."""
    return (
        np.exp(mean_log),
        np.exp(mean_log - Z95 * std_log),
        np.exp(mean_log + Z95 * std_log),
    )
