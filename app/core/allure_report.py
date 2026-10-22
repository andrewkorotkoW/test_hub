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
from datetime import datetime
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
    # stop_ts — момент завершения теста по allure (ISO, локальное время, как ts в run_events):
    # под xdist событий test_end в run_events нет, и это единственный источник времени
    # падения для волн (failure_causes.detect_waves).
    stop_ts = (
        datetime.fromtimestamp(stop / 1000.0).isoformat(timespec="seconds")
        if isinstance(stop, (int, float)) else None
    )
    # params — значения параметров pytest из allure `parameters` («tag», «blacklist»),
    # без кавычек, через дефис: fullName у allure-pytest параметров не содержит, а `name` —
    # это allure-заголовок (allure.title/dynamic.title), не pytest-имя. По params flaky
    # различает параметризованные кейсы (flaky.test_key).
    params = "-".join(
        str(p.get("value", "")).strip("'\"") for p in (data.get("parameters") or []) if isinstance(p, dict)
    )
    return {
        "name": data.get("fullName") or data.get("name") or path.stem,
        "params": params or None,
        "status": status if status in STATUSES else "unknown",
        "duration": duration,
        "stop_ts": stop_ts,
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


def _attempt_key(test: dict) -> str:
    return f"{test.get('name') or ''}[{test.get('params') or ''}]"


def final_attempts(tests: list[dict], repeat: int | None = 1) -> list[dict]:
    """Последняя попытка каждого теста (pytest-rerunfailures пишет несколько
    *-result.json с одним fullName): по максимальному stop_ts, без него — последняя
    по порядку. У оставленной записи поле attempts — сколько попыток было. Порядок —
    по первому появлению теста. Тот же выбор, что у DashboardChartsLogic.lastAttempts
    в UI; раньше повторы считались отдельными тестами и искажали counts/pass
    rate/флаки (прогон #96: 5 тестов, 7 строк, 57 %).

    repeat > 1 (RunCreate.repeat — «прогнать N раз» для флаки-детектора, см.
    runner._execute) — повторы намеренные и независимые: ничего не схлопываем,
    каждая запись возвращается как есть с attempts=1."""
    if repeat and repeat > 1:
        return [dict(test, attempts=1) for test in tests]
    by_key: dict[str, dict] = {}
    attempts: dict[str, int] = {}
    order: list[str] = []
    for test in tests:
        key = _attempt_key(test)
        attempts[key] = attempts.get(key, 0) + 1
        prev = by_key.get(key)
        if prev is None:
            order.append(key)
            by_key[key] = test
            continue
        newer = not test.get("stop_ts") or not prev.get("stop_ts") or str(test["stop_ts"]) >= str(prev["stop_ts"])
        if newer:
            by_key[key] = test
    result = []
    for key in order:
        entry = dict(by_key[key])
        entry["attempts"] = attempts[key]
        result.append(entry)
    return result


def counts_from_tests(tests: list[dict], repeat: int | None = 1) -> dict[str, int]:
    """Счётчики по финальным попыткам (final_attempts), а не по всем файлам результатов;
    repeat — как у final_attempts (при repeat > 1 считаются все записи)."""
    counts = _empty_counts()
    for test in final_attempts(tests, repeat):
        if test["status"] in counts:
            counts[test["status"]] += 1
    return counts
