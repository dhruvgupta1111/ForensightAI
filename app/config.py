import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
if len(JWT_SECRET_KEY.encode("utf-8")) < 32:
    raise RuntimeError(
        "JWT_SECRET_KEY must be configured with at least 32 bytes. "
        "See .env.example."
    )

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))
COOKIE_SECURE = (
    os.getenv("RENDER", "").strip().lower() == "true"
    or os.getenv("COOKIE_SECURE", "false").strip().lower() == "true"
)
DATABASE_PATH = Path(
    os.getenv("DATABASE_PATH", str(PROJECT_ROOT / "data" / "forensight.sqlite3"))
).expanduser()
PREDICTION_LOG_PATH = Path(
    os.getenv(
        "PREDICTION_LOG_PATH",
        str(PROJECT_ROOT / "data" / "prediction_logs.jsonl"),
    )
).expanduser()
