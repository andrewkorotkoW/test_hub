import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_allowed_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        ids.add(int(token))
    return ids


def _default_projects_root() -> Path:
    # На машине владельца test_hub и соседние проекты (bike_fit, Velo_bot,
    # auto_tests_vshgu — см. SEED_PROJECTS/VSHGU_PROJECT_PATH в app/db.py) лежат
    # в одной родительской папке PycharmProjects. BASE_DIR.parent воспроизводит
    # это только при обычном клонировании; если test_hub запущен из вложенного
    # git worktree (см. README про worktree-сессии), PycharmProjects — один из
    # более далёких предков, поэтому ищем его по имени, а не берём просто parent.
    for candidate in (BASE_DIR, *BASE_DIR.parents):
        if candidate.name == "PycharmProjects":
            return candidate
    return BASE_DIR.parent


class Settings:
    TH_PORT: int = int(os.getenv("TH_PORT", "8700"))
    TH_SECRET: str = os.getenv("TH_SECRET", "change-me")

    # 'dev' (по умолчанию, как сейчас у владельца) или 'prod' — переключает
    # проверку TH_SECRET и генерацию seed-паролей при старте (см. lifespan
    # в app/main.py и _seed_if_empty/_seed_superadmin в app/db.py).
    TH_ENV: str = os.getenv("TH_ENV", "dev")
    WORKSPACE_DIR: Path = BASE_DIR / "workspace"
    DB_PATH: Path = BASE_DIR / "workspace" / "test_hub.db"
    ALLURE_RESULTS_DIR: Path = BASE_DIR / "workspace" / "allure-results"
    ALLURE_REPORTS_DIR: Path = BASE_DIR / "workspace" / "allure-reports"
    FRAMES_DIR: Path = BASE_DIR / "workspace" / "frames"
    SESSION_COOKIE: str = "th_session"
    SESSION_MAX_AGE: int = 7 * 24 * 3600

    # Кадры UI-теста, присылаемые плагином проекта тестов (POST /api/runs/{id}/frames,
    # см. app/routers/runs.py) — лимит размера одного PNG и общего числа кадров на
    # прогон, чтобы случайно огромный/бесконечный поток скриншотов не забил диск.
    TH_FRAME_MAX_BYTES: int = int(os.getenv("TH_FRAME_MAX_BYTES", "2000000"))
    TH_FRAME_MAX_PER_RUN: int = int(os.getenv("TH_FRAME_MAX_PER_RUN", "500"))

    # Видео теста, присылаемое плагином проекта тестов после его завершения
    # (POST /api/runs/{id}/tests/{nodeid}/video, см. app/routers/runs.py) — лимит
    # размера одного файла, в мегабайтах (сравнивается как TH_VIDEO_MAX_MB * 1024 * 1024).
    TH_VIDEO_MAX_MB: int = int(os.getenv("TH_VIDEO_MAX_MB", "50"))

    # Эфир (живая трансляция UI-теста, POST .../runs с live=true) разрешён, только
    # если в прогоне не больше TH_LIVE_MAX_TESTS тестов (владелец, 01.10) — иначе
    # поток кадров/подписчики WS не выдержат. Число тестов считается через
    # runner.discover, как для дерева. Это же значение отдаётся фронту (GET /api/config).
    TH_LIVE_MAX_TESTS: int = int(os.getenv("TH_LIVE_MAX_TESTS", "20"))
    # workspace/runs/<run_id>/video/<hash>.webm — рядом с FRAMES_DIR, но отдельная
    # ветка (кадры шагов и финальное видео теста не смешиваются на диске).
    VIDEO_DIR: Path = BASE_DIR / "workspace" / "runs"

    # Лимит числа тестов в прогоне с галочкой «Эфир» (docs/missions/
    # 2026-10-01_live_stream.md, «Уточнение владельца 01.10») — форма запуска
    # запрещает галочку при большем числе выбранных тестов, POST .../runs дублирует
    # проверку на сервере (422).
    TH_LIVE_MAX_TESTS: int = int(os.getenv("TH_LIVE_MAX_TESTS", "20"))

    # Ручная загрузка скриншота к шагу тест-кейса (POST .../testcases/{id}/steps/{n}/
    # attachments, см. app/routers/test_cases.py) — лимит размера одного PNG/JPG.
    TH_TESTCASE_ATTACHMENT_MAX_BYTES: int = int(os.getenv("TH_TESTCASE_ATTACHMENT_MAX_BYTES", "5000000"))

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

    # Встроенный демо-сервис (demo/app/), на котором работает демо-проект Demo
    # (см. app/db.py) — test_hub поднимает его сам отдельным процессом (см.
    # lifespan в app/main.py). По умолчанию включён: цель — рабочий пример из
    # коробки сразу после клонирования, без реальных стендов.
    TH_DEMO: bool = _parse_bool(os.getenv("TH_DEMO", "1"))
    TH_DEMO_PORT: int = int(os.getenv("TH_DEMO_PORT", "8710"))

    # Sentry (см. app/core/sentry.py) — блок ошибок продукта для QA. Без заполненных
    # значений блок в UI показывает "Sentry не подключён" и ничего не ломает.
    TH_SENTRY_URL: str = os.getenv("TH_SENTRY_URL", "")
    TH_SENTRY_TOKEN: str = os.getenv("TH_SENTRY_TOKEN", "")
    TH_SENTRY_ORG: str = os.getenv("TH_SENTRY_ORG", "")

    # Явный путь к бинарнику allure CLI (см. app/core/allure_report.py), нужен генерация
    # Allure-отчёта для публичных ссылок (app/routers/share.py). Пусто = искать через
    # shutil.which("allure") и типичные каталоги установки — этого достаточно в обычном
    # терминале, но не для процесса под launchd/systemd с урезанным PATH (см. README).
    TH_ALLURE_BIN: str = os.getenv("TH_ALLURE_BIN", "")

    # Корень, где лежат соседние с test_hub проекты (см. _default_projects_root
    # выше и SEED_PROJECTS/VSHGU_PROJECT_PATH в app/db.py). В другом окружении
    # (CI, чужая машина) без переопределения такие пути просто не существуют, и
    # сиды по exists()-проверке пропускаются.
    TH_PROJECTS_ROOT: Path = Path(os.getenv("TH_PROJECTS_ROOT", str(_default_projects_root())))
    TH_VSHGU_PATH: Path = Path(os.getenv("TH_VSHGU_PATH", str(TH_PROJECTS_ROOT / "auto_tests_vshgu")))


settings = Settings()
