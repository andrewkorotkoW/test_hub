import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _parse_allowed_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        ids.add(int(token))
    return ids


class Settings:
    TH_PORT: int = int(os.getenv("TH_PORT", "8700"))
    TH_SECRET: str = os.getenv("TH_SECRET", "change-me")
    WORKSPACE_DIR: Path = BASE_DIR / "workspace"
    DB_PATH: Path = BASE_DIR / "workspace" / "test_hub.db"
    ALLURE_RESULTS_DIR: Path = BASE_DIR / "workspace" / "allure-results"
    ALLURE_REPORTS_DIR: Path = BASE_DIR / "workspace" / "allure-reports"
    SESSION_COOKIE: str = "th_session"
    SESSION_MAX_AGE: int = 7 * 24 * 3600

    # Базовый URL, по которому публичные ссылки на отчёты (см. app/routers/share.py)
    # видны снаружи процесса test_hub — не обязательно совпадает с TH_PORT/127.0.0.1
    # (за прокси/туннелем). Значение по умолчанию годится только для локальной разработки.
    TH_PUBLIC_URL: str = os.getenv("TH_PUBLIC_URL", "http://127.0.0.1:8700").rstrip("/")

    # Telegram-бот: пустой TH_TG_BOT_TOKEN полностью выключает бота (см. lifespan в
    # app/main.py); пустой TH_TG_ALLOWED_IDS означает "никому нельзя" (fail-safe), а
    # не "все разрешены".
    TH_TG_BOT_TOKEN: str = os.getenv("TH_TG_BOT_TOKEN", "")
    TH_TG_ALLOWED_IDS: set[int] = _parse_allowed_ids(os.getenv("TH_TG_ALLOWED_IDS", ""))
    TH_TG_SERVICE_LOGIN: str = os.getenv("TH_TG_SERVICE_LOGIN", "tg_bot")
    TH_TG_SERVICE_PASSWORD: str = os.getenv("TH_TG_SERVICE_PASSWORD", "tg_bot")


settings = Settings()
