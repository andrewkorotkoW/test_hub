"""Разбор allure-results (JSON-файлы *-result.json) в отчёт по прогону.

Адаптация логики ~/PycharmProjects/cyber_office/app/core/allure.py под test_hub:
здесь нет отдельного TestRun-объекта (статус/длительность хранятся в SQLite runs),
поэтому модуль занимается только разбором каталога allure-results в список тестов
и подсчёт по статусам."""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

from ..config import settings

STATUSES = ("passed", "failed", "broken", "skipped")

GENERATE_TIMEOUT_SECONDS = 60

logger = logging.getLogger(__name__)

# Каталоги, где allure CLI обычно оказывается после ручной установки (homebrew,
# распакованный zip-релиз в домашнюю папку) — их часто нет в PATH процесса, запущенного
# не из интерактивного терминала (launchd/systemd режут PATH до /usr/bin:/bin:...).
EXTRA_SEARCH_DIRS = ("/usr/local/bin", "/opt/homebrew/bin", str(Path.home() / ".local" / "bin"))


def _find_in_extra_dirs() -> str | None:
    for directory in EXTRA_SEARCH_DIRS:
        candidate = Path(directory) / "allure"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def resolve_allure_bin() -> str | None:
    """Путь к исполняемому файлу allure CLI: явный TH_ALLURE_BIN (если задан и указывает
    на реальный исполняемый файл) > PATH (shutil.which) > типичные каталоги установки
    (см. EXTRA_SEARCH_DIRS). Ничего не найдено — пишет в лог, где искали, и возвращает None."""
    configured = settings.TH_ALLURE_BIN
    if configured:
        if Path(configured).is_file() and os.access(configured, os.X_OK):
            return configured
        logger.warning("allure: TH_ALLURE_BIN=%s указывает не на исполняемый файл", configured)
        return None
    found = shutil.which("allure")
    if found:
        return found
    found = _find_in_extra_dirs()
    if found:
        return found
    logger.warning(
        "allure CLI не найден: PATH=%s, доп. каталоги=%s, TH_ALLURE_BIN не задан",
        os.environ.get("PATH", ""), ", ".join(EXTRA_SEARCH_DIRS),
    )
    return None


def allure_cli_available() -> bool:
    return resolve_allure_bin() is not None


def ensure_static_report(results_dir: Path, report_dir: Path) -> bool:
    """Гарантирует наличие сгенерированного `allure generate`-отчёта в report_dir
    (кэш на диске — генерация тяжелее простого разбора JSON). Возвращает True, если
    отчёт есть или был успешно сгенерирован, False — если allure CLI недоступен или
    генерация не удалась (тогда вызывающий код показывает встроенный отчёт test_hub)."""
    if (report_dir / "index.html").exists():
        return True
    if not results_dir.is_dir():
        return False
    allure_bin = resolve_allure_bin()
    if allure_bin is None:
        return False
    try:
        subprocess.run(
            [allure_bin, "generate", str(results_dir), "-o", str(report_dir), "--clean"],
            capture_output=True, timeout=GENERATE_TIMEOUT_SECONDS, check=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("allure generate (%s) завершился с ошибкой: %s", allure_bin, exc)
        return False
    return (report_dir / "index.html").exists()


def _empty_counts() -> dict[str, int]:
    return {status: 0 for status in STATUSES}


def _parse_result(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    status = data.get("status") or "unknown"
    start, stop = data.get("start"), data.get("stop")
    duration = (stop - start) / 1000.0 if isinstance(start, (int, float)) and isinstance(stop, (int, float)) else None
    details = data.get("statusDetails") or {}
    return {
        "name": data.get("fullName") or data.get("name") or path.stem,
        "status": status if status in STATUSES else "unknown",
        "duration": duration,
        "message": details.get("message"),
        "trace": details.get("trace"),
    }


def parse_results(results_dir: Path) -> list[dict]:
    if not results_dir.is_dir():
        return []
    tests = []
    for path in sorted(results_dir.glob("*-result.json")):
        parsed = _parse_result(path)
        if parsed is not None:
            tests.append(parsed)
    return tests


def counts_from_tests(tests: list[dict]) -> dict[str, int]:
    counts = _empty_counts()
    for test in tests:
        if test["status"] in counts:
            counts[test["status"]] += 1
    return counts
