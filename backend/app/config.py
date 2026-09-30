"""Runtime settings, read from environment variables (see docker-compose.yml)."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ML_DIR = BASE_DIR / "ml_modules"


class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://healthbridge:healthbridge@localhost:5432/healthbridge"
    )
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-only-change-me")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "720"))
    cors_origins: list[str] = [
        o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()
    ]
    upload_dir: Path = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads")))
    seed_demo: bool = os.getenv("SEED_DEMO", "false").lower() == "true"

    # Member 1's cost model (US insurance.csv) and Member 2's fraud model
    # (synthetic claims) were trained on USD-scale numbers; the platform works
    # in INR, so the ML adapters convert at this rate.
    usd_to_inr: float = float(os.getenv("USD_TO_INR", "83.0"))


settings = Settings()
