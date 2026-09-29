-- Schema for the AAPL forecast platform.
-- Runs automatically the first time the Postgres container starts.

CREATE TABLE IF NOT EXISTS stock_prices (
    symbol      VARCHAR(16)      NOT NULL,
    trade_date  DATE             NOT NULL,
    open        DOUBLE PRECISION,
    high        DOUBLE PRECISION,
    low         DOUBLE PRECISION,
    close       DOUBLE PRECISION NOT NULL,
    adj_close   DOUBLE PRECISION,
    volume      BIGINT,
    source      VARCHAR(128),
    PRIMARY KEY (symbol, trade_date)
);

-- One row per training run of one model (holds back-test metrics).
CREATE TABLE IF NOT EXISTS model_runs (
    id            BIGSERIAL PRIMARY KEY,
    symbol        VARCHAR(16)  NOT NULL,
    model_name    VARCHAR(64)  NOT NULL,
    trained_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    train_start   DATE,
    train_end     DATE,
    test_days     INT,
    mae           DOUBLE PRECISION,
    rmse          DOUBLE PRECISION,
    mape          DOUBLE PRECISION,
    direction_acc DOUBLE PRECISION,
    is_best       BOOLEAN      NOT NULL DEFAULT FALSE,
    params        JSONB
);
CREATE INDEX IF NOT EXISTS ix_model_runs_symbol_time ON model_runs (symbol, trained_at DESC);

-- A forecast request / result header.
CREATE TABLE IF NOT EXISTS forecasts (
    id           BIGSERIAL PRIMARY KEY,
    symbol       VARCHAR(16) NOT NULL,
    model_name   VARCHAR(64) NOT NULL,
    horizon      INT         NOT NULL,
    base_date    DATE        NOT NULL,
    base_close   DOUBLE PRECISION NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_forecasts_symbol_time ON forecasts (symbol, created_at DESC);

CREATE TABLE IF NOT EXISTS forecast_points (
    forecast_id  BIGINT NOT NULL REFERENCES forecasts(id) ON DELETE CASCADE,
    step         INT    NOT NULL,
    target_date  DATE   NOT NULL,
    predicted    DOUBLE PRECISION NOT NULL,
    lower        DOUBLE PRECISION NOT NULL,
    upper        DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (forecast_id, step)
);

-- Tracked stocks (kept in sync from ml-service/app/symbols.py when the ml service starts).
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
);
