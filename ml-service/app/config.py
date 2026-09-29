import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://aapl:aapl@localhost:5432/aapl_forecast")
DATA_DIR = os.getenv("DATA_DIR", "/data/raw")
MODEL_DIR = os.getenv("MODEL_DIR", "/data/models")
SYMBOL = os.getenv("SYMBOL", "AAPL")
TEST_DAYS = int(os.getenv("TEST_DAYS", "60"))
EVAL_HORIZON = int(os.getenv("EVAL_HORIZON", "5"))
