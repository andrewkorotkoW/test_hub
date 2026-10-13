"""Классификатор причин падения тестов (троттлинг/потеря сессии/стенд не ответил/
код) и обнаружение волн инфраструктурных сбоев — ядро вкладки «Причины» и
«Сравнить с…» окна прогона (docs/missions/2026-10-13_run_compare_and_causes.md).

classify() решает по тексту allure statusDetails.message/trace, к какой причине
относится падение. Приоритет throttling > session > stand > code: 429 от стенда
часто тянет за собой LoginError (сессия не поднялась из-за троттлинга), поэтому
троттлинг проверяется первым. Любая ошибка внутри classify гасится и превращается
в 'code' — классификатор не должен ронять _finalize (app/core/runner.py).

Результат классификации каждого теста прогона кэшируется в таблице
run_test_results (app.db.SCHEMA) функцией record_run_results — она вызывается
раннером сразу после завершения прогона (app/core/runner.py::_finalize, рядом с
flaky.recalc) и получает уже готовое сопоставление nodeid -> fullName (строится
через runner.discover(), поэтому сама record_run_results не импортирует runner —
это сделало бы цикл runner -> failure_causes -> runner). Для прогонов, у которых
строк в run_test_results ещё нет (старые, до этой задачи), ensure_run_results
лениво пересчитывает их по allure-results на диске при первом обращении к
GET /runs/{id}/causes или /compare — там модуль runner уже можно импортировать
локально внутри функции (тот же приём, что app.core.schedule._notification_caption
использует для app.tg_bot, не желая зависеть от него на уровне модуля)."""
from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from ..config import settings
from ..db import get_connection
from . import allure_report

logger = logging.getLogger(__name__)

MAX_REASON_LEN = 120

INFRA_CAUSES = ("throttling", "session", "stand")
ALL_CAUSES = (*INFRA_CAUSES, "code")

WAVE_MIN_COUNT = 5
WAVE_WINDOW = timedelta(minutes=2)

PATTERNS: dict[str, tuple[re.Pattern, ...]] = {
    "throttling": (
        re.compile(r"\b429\b"),
        re.compile(r"Too Many Requests", re.IGNORECASE),
        re.compile(r"X-RateLimit", re.IGNORECASE),
        # сессия не поднялась из-за троттлинга логина в k8s-стенде, см. memory
        re.compile(r"LoginError[\s\S]*K8S_LOGIN", re.IGNORECASE),
    ),
    "session": (
        re.compile(r"\b401\b"),
        re.compile(r"Unauthenticated", re.IGNORECASE),
        re.compile(r"Unauthorized", re.IGNORECASE),
        re.compile(r"/auth/main", re.IGNORECASE),
    ),
    "stand": (
        re.compile(r"\b5\d\d\b"),
        re.compile(r"ReadTimeout", re.IGNORECASE),
        re.compile(r"ConnectTimeout", re.IGNORECASE),
        re.compile(r"RemoteDisconnected", re.IGNORECASE),
        re.compile(r"Connection reset", re.IGNORECASE),
        re.compile(r"ECONNREFUSED", re.IGNORECASE),
        re.compile(r"Gateway", re.IGNORECASE),
        # "Timeout 30000ms exceeded" сам по себе бывает и на локаторе (это 'code') —
        # считаем стендом, только если рядом речь о навигации/ожидании ответа сети
        re.compile(r"(?=[\s\S]*Timeout 30000ms exceeded)(?=[\s\S]*(?:goto|expect_response))"),
    ),
}

# tests/ui/ai_chat/** — таймаут означает, что LLM-стенд за 180с не ответил, а не
# баг теста; сообщения там не всегда укладываются в паттерны 'stand' выше (может
# не быть ровно "Timeout 30000ms exceeded"), поэтому разрешаем общий признак
# таймаута по nodeid, а не только по конкретной подстроке.
_AI_CHAT_NODEID_RE = re.compile(r"(?:^|/)tests/ui/ai_chat/")
_TIMEOUT_HINT_RE = re.compile(r"timeout|таймаут|exceeded", re.IGNORECASE)


def classify(message: str | None, trace: str | None, nodeid: str | None = None) -> str:
    try:
        text = "\n".join(part for part in (message, trace) if part)
        for cause in INFRA_CAUSES:
            if any(pattern.search(text) for pattern in PATTERNS[cause]):
                return cause
        if nodeid and _AI_CHAT_NODEID_RE.search(nodeid) and _TIMEOUT_HINT_RE.search(text):
            return "stand"
        return "code"
    except Exception:
        logger.exception("failure_causes.classify упал на nodeid=%s — считаем 'code'", nodeid)
        return "code"


def short_reason(message: str | None) -> str:
    """Первая строка сообщения об ошибке, обрезанная до MAX_REASON_LEN — общая
    логика для GET /runs/{id}/causes и app/tg_bot/formatting.py::_short_reason."""
    text = (message or "").strip()
    if not text:
        return ""
    return text.splitlines()[0][:MAX_REASON_LEN]


# ------------------------------------------------------------------ волны
def detect_waves(results: list[dict]) -> list[dict]:
    """results — записи с полями 'cause' и 'finished_ts' (ISO-строка или None), как
    строки run_test_results. Волна — это непрерывный (по времени) участок падений
    одной инфраструктурной причины, где у каждой входящей в него точки есть окно
    не длиннее WAVE_WINDOW, покрывающее не менее WAVE_MIN_COUNT падений этой же
    причины — соседние такие окна сами склеиваются в один участок, т.к. покрывают
    общие точки."""
    waves: list[dict] = []
    for cause in INFRA_CAUSES:
        timestamps = sorted(
            ts
            for ts in (
                _parse_ts(r.get("finished_ts"))
                for r in results
                if r.get("cause") == cause
            )
            if ts is not None
        )
        waves.extend(_cause_waves(cause, timestamps))
    waves.sort(key=lambda w: w["start_ts"])
    return waves


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _cause_waves(cause: str, timestamps: list[datetime]) -> list[dict]:
    """Для каждой точки — максимальное окно (anchor=i, пока следующая точка
    укладывается в WAVE_WINDOW от неё), которое набирает WAVE_MIN_COUNT точек.
    Такие кандидатские (i, j)-диапазоны индексов сортированного по времени ряда
    затем сливаются как обычные интервалы: соседние окна (у одной причины) могут
    перекрываться по индексам только если они физически близки по времени — две
    волны, разделённые большим разрывом (как в #66), дают непересекающиеся по
    индексам диапазоны и не склеиваются."""
    n = len(timestamps)
    candidates: list[tuple[int, int]] = []
    for i in range(n):
        j = i
        while j + 1 < n and timestamps[j + 1] - timestamps[i] <= WAVE_WINDOW:
            j += 1
        if j - i + 1 >= WAVE_MIN_COUNT:
            candidates.append((i, j))
    if not candidates:
        return []

    merged = [candidates[0]]
    for start, end in candidates[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    return [
        {
            "cause": cause,
            "start_ts": timestamps[i].isoformat(timespec="seconds"),
            "end_ts": timestamps[j].isoformat(timespec="seconds"),
            "count": j - i + 1,
        }
        for i, j in merged
    ]


# ------------------------------------------------------------------ сохранение результатов прогона
def _nodeid_to_full_name(nodeid: str) -> str:
    """pytest nodeid -> allure fullName. Своя копия по тому же соглашению модулей,
    что и app/routers/runs.py/app/core/flaky.py (allure_pytest.utils.allure_full_name):
    не тянуть межмодульную зависимость ради одной функции."""
    file_part, _, rest = nodeid.partition("::")
    module = file_part[:-3] if file_part.endswith(".py") else file_part
    module = module.replace("/", ".")
    if not rest:
        return module
    segments = rest.split("::")
    test = segments[-1].split("[")[0]
    class_name = f".{segments[-2]}" if len(segments) > 1 else ""
    return f"{module}{class_name}#{test}"


def _full_name_index(tree: dict) -> dict[str, str]:
    index: dict[str, str] = {}
    for file_path, classes in tree.items():
        for cls_name, tests in classes.items():
            for test_name in tests:
                nodeid = f"{file_path}::{cls_name}::{test_name}" if cls_name else f"{file_path}::{test_name}"
                index.setdefault(_nodeid_to_full_name(nodeid), nodeid)
    return index


def _allure_dir(run_id: int) -> Path:
    return settings.ALLURE_RESULTS_DIR / str(run_id)


def _test_end_timestamps(run_id: int) -> dict[str, str]:
    """nodeid -> ts последнего события test_end этого прогона (ORDER BY id — при
    реранах внутри одного прогона последняя запись побеждает, то же допущение,
    что и ниже при выборе финального статуса из allure_report.parse_results)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT nodeid, ts FROM run_events WHERE run_id = ? AND kind = 'test_end' "
            "AND nodeid IS NOT NULL ORDER BY id",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    return {row["nodeid"]: row["ts"] for row in rows}


def record_run_results(
    run_id: int, project: str, stand: str | None, nodeid_by_full_name: dict[str, str]
) -> None:
    """Пишет run_test_results для завершённого прогона, по одной строке на
    nodeid (PK run_id+nodeid). Рерайт-дубликаты (несколько *-result.json с одним
    fullName внутри одного прогона, см. app.core.flaky.recalc) не накапливаются —
    берётся последняя запись allure_report.parse_results для этого nodeid, как
    финальный статус после реранов. cause считается только для failed/broken —
    остальным статусам он не нужен и не должен засорять сводку по причинам.

    Ошибка внутри — ловится целиком и пишется в лог, run_test_results для этого
    прогона просто не обновится (вызывающая сторона, _finalize, не должна упасть)."""
    try:
        results = allure_report.parse_results(_allure_dir(run_id))
        # parse_results отдаёт файлы в порядке имён (uuid) — для теста с реранами это
        # случайный порядок, и «последняя запись побеждает» давала финальный статус
        # наугад: у run 66 выходило 129 падений вместо 96 из runs.counts. Сортируем по
        # времени завершения, чтобы последней была действительно последняя попытка.
        results.sort(key=lambda e: e.get("stop_ts") or "")
        finished_ts_by_nodeid = _test_end_timestamps(run_id)

        conn = get_connection()
        try:
            conn.execute("DELETE FROM run_test_results WHERE run_id = ?", (run_id,))
            for entry in results:
                full_name = entry["name"]
                nodeid = nodeid_by_full_name.get(full_name, full_name)
                test_status = entry["status"]
                cause = classify(entry.get("message"), entry.get("trace"), nodeid) \
                    if test_status in ("failed", "broken") else None
                conn.execute(
                    "INSERT OR REPLACE INTO run_test_results "
                    "(run_id, nodeid, full_name, status, duration, cause, finished_ts) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id, nodeid, full_name, test_status, entry.get("duration"), cause,
                        # Под xdist (stands.workers > 0) раннер не пишет test_end — статусы
                        # есть только в «[gwN] … STATUS nodeid»-строках, и без запасного
                        # времени из allure волны 429 на k8s (run 66) не находились вовсе.
                        finished_ts_by_nodeid.get(nodeid) or entry.get("stop_ts"),
                    ),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception("record_run_results упал для run_id=%s (project=%s, stand=%s)", run_id, project, stand)


async def ensure_run_results(run_id: int) -> None:
    """Ленивый пересчёт для прогонов без строк в run_test_results (запущенных до
    этой задачи) — вызывается перед построением ответа GET /runs/{id}/causes и
    GET /runs/{id}/compare. runner импортируется локально (не на уровне модуля),
    см. докстринг модуля — иначе получился бы цикл runner -> failure_causes ->
    runner (runner.py импортирует failure_causes для record_run_results)."""
    conn = get_connection()
    try:
        exists = conn.execute(
            "SELECT 1 FROM run_test_results WHERE run_id = ? LIMIT 1", (run_id,)
        ).fetchone()
        if exists is not None:
            return
        run_row = conn.execute("SELECT project, stand, status FROM runs WHERE id = ?", (run_id,)).fetchone()
        if run_row is None or run_row["status"] not in ("passed", "failed", "cancelled"):
            return
        project_row = conn.execute(
            "SELECT path, venv FROM projects WHERE name = ?", (run_row["project"],)
        ).fetchone()
    finally:
        conn.close()

    nodeid_by_full_name: dict[str, str] = {}
    if project_row is not None:
        try:
            from . import runner  # ленивый импорт, см. докстринг модуля/функции

            discovered = await runner.discover(project_row["path"], project_row["venv"])
            nodeid_by_full_name = _full_name_index(discovered.get("tree") or {})
        except Exception:
            logger.exception("ensure_run_results: discover упал для run_id=%s", run_id)

    await asyncio.to_thread(record_run_results, run_id, run_row["project"], run_row["stand"], nodeid_by_full_name)


# ------------------------------------------------------------------ выбор базового прогона для сравнения
def prev_run_id_on_stand(conn: sqlite3.Connection, project: str, stand: str | None, before_run_id: int) -> int | None:
    """Прогон, непосредственно предшествующий before_run_id на том же стенде —
    для столбца «Δ к предыдущему» в «Истории» (GET /api/projects/{name}/runs) и
    как запасной вариант базы сравнения в default_base_run_id ниже."""
    row = conn.execute(
        "SELECT id FROM runs WHERE project = ? AND stand IS ? AND id < ? "
        "AND status IN ('passed', 'failed', 'cancelled') ORDER BY id DESC LIMIT 1",
        (project, stand, before_run_id),
    ).fetchone()
    return row["id"] if row else None


def default_base_run_id(
    conn: sqlite3.Connection, project: str, stand: str | None, target: str | None, marker: str | None,
    exclude_run_id: int,
) -> int | None:
    """Предыдущий завершённый прогон того же проекта/стенда с тем же target и
    marker; если такого нет — предыдущий завершённый прогон на том же стенде
    (независимо от target/marker). IS вместо = — stand/target/marker допускают
    NULL, а SQLite IS корректно сравнивает NULL с NULL и значение со значением
    одним и тем же выражением."""
    row = conn.execute(
        "SELECT id FROM runs WHERE project = ? AND stand IS ? AND target IS ? AND marker IS ? "
        "AND id < ? AND status IN ('passed', 'failed', 'cancelled') ORDER BY id DESC LIMIT 1",
        (project, stand, target, marker, exclude_run_id),
    ).fetchone()
    if row is not None:
        return row["id"]
    return prev_run_id_on_stand(conn, project, stand, exclude_run_id)


def stand_failure_count(run_id: int) -> int:
    """Сколько падений прогона классифицированы как инфраструктурные (throttling/
    session/stand) — используется и в delta_prev «Истории», и в сводке /causes.
    Для прогона без строк в run_test_results (ещё не пересчитан лениво) — 0, это
    не блокер: лениво пересчитывается при открытии вкладки «Причины»/«Сравнить»."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM run_test_results WHERE run_id = ? AND cause IN (?, ?, ?)",
            (run_id, *INFRA_CAUSES),
        ).fetchone()
        return row["c"] if row else 0
    finally:
        conn.close()
