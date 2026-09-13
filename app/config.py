import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    TH_PORT: int = int(os.getenv("TH_PORT", "8700"))
    TH_SECRET: str = os.getenv("TH_SECRET", "change-me")
    WORKSPACE_DIR: Path = BASE_DIR / "workspace"
    DB_PATH: Path = BASE_DIR / "workspace" / "test_hub.db"
    ALLURE_RESULTS_DIR: Path = BASE_DIR / "workspace" / "allure-results"
    SESSION_COOKIE: str = "th_session"
    SESSION_MAX_AGE: int = 7 * 24 * 3600


settings = Settings()
