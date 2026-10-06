"""Тест-кейсы: собственная таблица test_cases поверх markdown-черновиков
auto_tests_vshgu (`docs/test_cases/*.md`, см. `tools/test_cases/testit_sync.py::
parse_area_file` в том репозитории — парсер здесь портирован под test_hub) и/или
ручного заведения.

Второй источник истины поверх allure, ровно по прецеденту app.core.xfail_registry:
import_drafts() апсертит записи по ключу (project, case_key) с source='generated',
запись с source='manual' (выставляется update_case() при первой ручной правке)
повторным импортом не затирается — тот же приём, что recalc() в xfail_registry не
затирает issue_url/note. case_key — nodeid (кейсы с автотестом) либо TC-ID из
заголовка `### TC-XXX-NNN …` (ручные кейсы без автотеста, см. CASE_ID_RE) —
кейсы без автотеста в черновиках такой же полноправный источник, просто без
привязки к nodeid.

Статус последнего прогона довешивается тем же способом, что и в xfail_registry/
flaky/coverage: nodeid -> allure fullName -> поиск в allure-results последнего
завершённого прогона стенда (app.core.stats.default_stand/latest_finished_run_id,
app.core.allure_report.parse_results).

Скриншоты шагов (test_case_attachments, source in ('allure', 'manual')):
- sync_run_attachments() вызывается раннером после каждого завершённого прогона
  (app.core.runner.py::_finalize, рядом с xfail_registry.recalc — тем же приёмом:
  asyncio.to_thread, своя БД-коннекция, независимо от остальных пересчётов). Для
  каждого кейса проекта с nodeid, чей allure fullName встречается среди
  *-result.json этого прогона, собирает image-вложения (type/mime image/png или
  image/jpeg) и заменяет ими предыдущие attachments с source='allure' этого кейса
  (и в БД, и на диске) — это синхронизация состояния "на последний прогон", а не
  накопление. Тесты, не участвовавшие в прогоне, не трогаются — их старые
  allure-скриншоты остаются от прошлого прогона, где эти тесты выполнялись.
  Привязка к шагу: allure_pytest кладёт вложения шага в `steps[i].attachments`
  (i — 0-based позиция в списке шагов результата) — это лишь приближённое
  сопоставление с шагами test_cases (allure не хранит номер шага test_hub),
  используется порядковый номер step_n = i + 1. Вложения теста целиком, не
  привязанные ни к какому шагу (`attachments` на верхнем уровне *-result.json),
  получают step_n = 0 — в карточке кейса это общие вложения (значение выбрано
  вместо NULL: колонка test_case_attachments.step_n NOT NULL). Вложенные
  под-шаги (steps[i].steps) не разворачиваются — на практике плагины test_hub
  кладут скриншоты шага ровно на первый уровень steps[].
- add_manual_attachment()/delete_manual_attachment() — ручная загрузка/удаление
  через API (app/routers/test_cases.py), source='manual'; автосинхронизация их
  не трогает."""
from __future__ import annotations

import json
import mimetypes
import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from ..config import settings
from ..db import get_connection
from . import allure_report, stats

TEMPLATE_FILE = "TEMPLATE.md"
UPDATE_MARK = "<!-- обновить -->"

HEADING_RE = re.compile(r"^### (TC-[A-Za-z0-9_]+-\d+)\s+(.+)$")
# Тот же алфавит, что у HEADING_RE: области вида TC-HELPDESK_GROUPS-001 (с «_») —
# иначе ручной кейс без автотеста получает case_id=None и молча пропускается импортом.
CASE_ID_RE = re.compile(r"TC-[A-Za-z0-9_]+-\d+")
AUTOTEST_RE = re.compile(r"^-\s*Автотест:\s*(\S+)\s*$")
META_RE = re.compile(r"^-\s*Приоритет:\s*(\S+)\s+Тип:\s*(\S+)\s+Роли:\s*(.*)$")
PRECONDITION_RE = re.compile(r"^-\s*Предусловия:\s*(.*)$")
REQUIREMENT_RE = re.compile(r"^-\s*Требование:\s*(.*)$")

TESTCASES_DIR = settings.WORKSPACE_DIR / "testcases"

_IMAGE_MIME_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg"}
_EXTENSION_MIME_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


class UnsupportedAttachmentType(Exception):
    """Загружаемый файл — не PNG/JPG (ни по расширению, ни по mime-типу)."""


class NotManualAttachment(Exception):
    """Попытка удалить через API вложение с source='allure' — оно управляется
    только автосинхронизацией (sync_run_attachments), не ручным DELETE."""


def attachments_dir(project: str, case_id: int) -> Path:
    return TESTCASES_DIR / project / str(case_id)


def _attachment_url(project: str, case_id: int, attachment_id: int) -> str:
    return f"/api/projects/{project}/testcases/{case_id}/attachments/{attachment_id}"


# ------------------------------------------------------------------ парсер markdown-черновиков


def _parse_table_row(line: str) -> tuple[str, str] | None:
    """"| 1 | действие | ожидаемый результат |" -> ("действие", "ожидаемый результат")."""
    line = line.strip()
    if not line.startswith("|") or not line.endswith("|"):
        return None
    parts = [p.strip() for p in line[1:-1].split("|")]
    if len(parts) != 3 or not parts[0].isdigit():
        return None
    return parts[1].replace("\\|", "|"), parts[2].replace("\\|", "|")


def _parse_case_block(block: list[str]) -> dict | None:
    heading = HEADING_RE.match(block[0])
    if heading is None:
        return None
    title = heading.group(2).strip()
    if title.endswith(UPDATE_MARK):
        title = title[: -len(UPDATE_MARK)].strip()
    case_id_match = CASE_ID_RE.search(heading.group(1))
    case_id = case_id_match.group(0) if case_id_match else None

    nodeid: str | None = None
    priority = "medium"
    precondition: str | None = None
    requirement: str | None = None
    steps: list[dict] = []

    for line in block[1:]:
        stripped = line.strip()
        m = AUTOTEST_RE.match(stripped)
        if m:
            nodeid = m.group(1)
            continue
        m = META_RE.match(stripped)
        if m:
            priority = m.group(1).lower()
            continue
        m = PRECONDITION_RE.match(stripped)
        if m:
            precondition = m.group(1).strip() or None
            continue
        m = REQUIREMENT_RE.match(stripped)
        if m:
            requirement = m.group(1).strip() or None
            continue
        row = _parse_table_row(stripped)
        if row:
            steps.append({"action": row[0], "expected": row[1]})

    return {
        "title": title,
        "case_id": case_id,
        "nodeid": nodeid,
        "priority": priority,
        "precondition": precondition,
        "requirement": requirement,
        "steps": steps,
    }


def parse_area_file(path: Path) -> list[dict]:
    """Черновик области (`docs/test_cases/<area>.md` или `docs/test_cases/<area>/<file>.md`)
    -> список кейсов {title, case_id, nodeid, priority, precondition, requirement,
    steps: [{action, expected}]}. case_id — идентификатор из заголовка (TC-XXX-NNN,
    см. CASE_ID_RE), nodeid — None для кейсов без строки "Автотест:".
    Портировано из auto_tests_vshgu `tools/test_cases/testit_sync.py::parse_area_file`,
    без полей, которых нет в схеме test_hub (тип/роли/steps-hash/Test IT id)."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    heading_idx = [i for i, l in enumerate(lines) if HEADING_RE.match(l)]

    cases = []
    for pos, start in enumerate(heading_idx):
        end = heading_idx[pos + 1] if pos + 1 < len(heading_idx) else len(lines)
        block = lines[start:end]
        while block and block[-1].strip() == "":
            block.pop()
        case = _parse_case_block(block)
        if case:
            cases.append(case)
    return cases


def _numbered_steps(raw_steps: list[dict]) -> list[dict]:
    return [
        {"n": i + 1, "action": s["action"], "expected": s["expected"], "attachments": []}
        for i, s in enumerate(raw_steps)
    ]


def _section_from_nodeid(nodeid: str) -> str:
    """Раздел кейса тем же приёмом, что и app.core.sections.discover(): nodeid
    `tests/api/buk/test_x.py::...` -> "api/buk" (у e2e — один раздел "e2e" без
    разбивки на области, см. app.core.sections/app.core.stats)."""
    file_part = nodeid.split("::", 1)[0]
    parts = Path(file_part).parts
    if parts and parts[0] == "tests":
        parts = parts[1:]
    if not parts:
        return "misc"
    kind = parts[0]
    if kind in ("api", "ui"):
        return f"{kind}/{parts[1]}" if len(parts) > 1 else kind
    if kind == "e2e":
        return "e2e"
    return kind


# ------------------------------------------------------------------ импорт черновиков


def _rel_subdir(path: Path, root: Path) -> str:
    """Путь `path` относительно `root` без имени файла: "" — файл лежит прямо в
    `root`, иначе относительный путь подпапки в posix-виде ("mts_link")."""
    rel_dir = path.parent.relative_to(root)
    return "" if rel_dir == Path(".") else rel_dir.as_posix()


def _case_key(case: dict) -> str | None:
    """Ключ идентичности кейса для апсерта: nodeid — для кейсов с автотестом,
    иначе TC-ID из заголовка (case_id, см. CASE_ID_RE). None — у заголовка нет
    ни того, ни другого (такой кейс не с чем сопоставлять повторно, просто
    каждый раз вставляется новой строкой)."""
    return case["nodeid"] or case["case_id"]


def _section_for_case(case: dict, subdir: str, file_stem: str) -> str:
    """Раздел кейса в дереве test_cases. С nodeid — как раньше, по пути автотеста
    (_section_from_nodeid), но если черновик лежит в подпапке
    docs/test_cases/<subdir>/..., <subdir> становится верхним уровнем секции.
    Без nodeid (ручной кейс без автотеста) раздел строится из расположения
    самого файла-черновика: <subdir>/<имя файла без расширения> — например,
    файл docs/test_cases/mts_link/02_create.md даёт секцию "mts_link/02_create"
    (в дереве — верхний уровень "mts_link", область "02_create")."""
    if case["nodeid"]:
        base = _section_from_nodeid(case["nodeid"])
        return f"{subdir}/{base}" if subdir else base
    return f"{subdir}/{file_stem}" if subdir else file_stem


def import_drafts(conn: sqlite3.Connection, project_row: sqlite3.Row) -> dict:
    """Читает `<project.path>/docs/test_cases/**/*.md` (рекурсивно, TEMPLATE.md
    пропускается в любой подпапке), апсертит test_cases по ключу
    (project, case_key) с source='generated' — и для кейсов с автотестом
    (case_key = nodeid), и для ручных кейсов без него (case_key = TC-ID из
    заголовка, см. _case_key). Записи с уже выставленным source='manual' не
    трогает — повторный импорт не должен затирать ручные правки (см. описание
    модуля)."""
    docs_dir = Path(project_row["path"]) / "docs" / "test_cases"
    result = {"files": 0, "imported": 0, "updated": 0, "skipped_manual": 0}
    if not docs_dir.is_dir():
        return result

    project = project_row["name"]
    now = datetime.now().isoformat(timespec="seconds")

    for path in sorted(docs_dir.rglob("*.md")):
        if path.name == TEMPLATE_FILE:
            continue
        result["files"] += 1
        subdir = _rel_subdir(path, docs_dir)
        file_stem = path.stem
        for case in parse_area_file(path):
            case_key = _case_key(case)
            if not case_key:
                continue
            existing = conn.execute(
                "SELECT * FROM test_cases WHERE project = ? AND case_key = ?", (project, case_key)
            ).fetchone()
            # Кейс был ручным (ключ TC-ID), а теперь получил «- Автотест:» (ключ nodeid) —
            # подхватываем старую строку и переводим её на новый ключ, иначе импорт
            # создаёт дубль, а ручная запись остаётся сиротой (06.10.2026, helpdesk).
            if existing is None and case["nodeid"] and case["case_id"]:
                existing = conn.execute(
                    "SELECT * FROM test_cases WHERE project = ? AND case_key = ?", (project, case["case_id"])
                ).fetchone()
            if existing and existing["source"] == "manual":
                result["skipped_manual"] += 1
                continue

            section = _section_for_case(case, subdir, file_stem)
            steps_json = json.dumps(_numbered_steps(case["steps"]), ensure_ascii=False)
            # Строка по nodeid уже есть, а рядом осталась старая ручная копия этого же кейса
            # по TC-ID (импорт до фикса выше) — убираем сироту, ручные правки не трогаем.
            if case["nodeid"] and case["case_id"] and case_key != case["case_id"]:
                conn.execute(
                    "DELETE FROM test_cases WHERE project = ? AND case_key = ? AND source != 'manual' AND id != ?",
                    (project, case["case_id"], existing["id"] if existing else -1),
                )
            if existing:
                conn.execute(
                    "UPDATE test_cases SET section = ?, title = ?, steps = ?, precondition = ?, priority = ?, "
                    "requirement = ?, nodeid = ?, case_key = ?, source = 'generated', updated_at = ? WHERE id = ?",
                    (
                        section, case["title"], steps_json, case["precondition"], case["priority"],
                        case["requirement"], case["nodeid"], case_key, now, existing["id"],
                    ),
                )
                result["updated"] += 1
            else:
                conn.execute(
                    "INSERT INTO test_cases "
                    "(project, section, title, steps, precondition, priority, nodeid, case_key, requirement, "
                    "source, updated_at, updated_by) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'generated', ?, NULL)",
                    (
                        project, section, case["title"], steps_json, case["precondition"], case["priority"],
                        case["nodeid"], case_key, case["requirement"], now,
                    ),
                )
                result["imported"] += 1

    conn.commit()
    return result


# ------------------------------------------------------------------ ручное создание/правка


def create_manual(
    conn: sqlite3.Connection,
    project: str,
    section: str,
    title: str,
    precondition: str | None,
    priority: str,
    steps: list[dict],
    nodeid: str | None,
    user_login: str,
) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    steps_json = json.dumps(_numbered_steps(steps), ensure_ascii=False)
    cur = conn.execute(
        "INSERT INTO test_cases "
        "(project, section, title, steps, precondition, priority, nodeid, source, updated_at, updated_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'manual', ?, ?)",
        (project, section, title, steps_json, precondition, priority, nodeid, now, user_login),
    )
    conn.commit()
    return get_case(conn, project, cur.lastrowid)


def update_case(
    conn: sqlite3.Connection,
    case_id: int,
    title: str,
    precondition: str | None,
    priority: str,
    steps: list[dict],
    nodeid: str | None,
    user_login: str,
) -> dict | None:
    row = conn.execute("SELECT project FROM test_cases WHERE id = ?", (case_id,)).fetchone()
    if row is None:
        return None
    now = datetime.now().isoformat(timespec="seconds")
    steps_json = json.dumps(_numbered_steps(steps), ensure_ascii=False)
    conn.execute(
        "UPDATE test_cases SET title = ?, precondition = ?, priority = ?, steps = ?, nodeid = ?, "
        "source = 'manual', updated_at = ?, updated_by = ? WHERE id = ?",
        (title, precondition, priority, steps_json, nodeid, now, user_login, case_id),
    )
    conn.commit()
    return get_case(conn, row["project"], case_id)


# ------------------------------------------------------------------ статус последнего прогона


def _allure_dir(run_id: int) -> Path:
    return settings.ALLURE_RESULTS_DIR / str(run_id)


def _nodeid_to_full_name(nodeid: str) -> str:
    """pytest nodeid -> allure fullName. Своя копия по тому же соглашению модулей,
    что и app.core.flaky/coverage/xfail_registry (app/core/xfail_registry.py:243-256)."""
    file_part, _, rest = nodeid.partition("::")
    module = file_part[:-3] if file_part.endswith(".py") else file_part
    module = module.replace("/", ".")
    if not rest:
        return module
    segments = rest.split("::")
    test = segments[-1].split("[")[0]
    class_name = f".{segments[-2]}" if len(segments) > 1 else ""
    return f"{module}{class_name}#{test}"


def _bucket_status(entry: dict) -> str:
    """passed/failed/xfail/skipped — своя копия app.core.stats._bucket_status
    (broken схлопывается в failed, xfail — по префиксу "xfail" в message)."""
    status = entry["status"]
    if status == "broken":
        return "failed"
    if status == "skipped" and entry.get("message") and "xfail" in entry["message"].lower():
        return "xfail"
    return status


def _status_map(conn: sqlite3.Connection, project: str) -> dict[str, str]:
    """allure fullName -> статус, по последнему завершённому прогону стенда по
    умолчанию (app.core.stats.default_stand — тот же выбор, что у /stats)."""
    stand = stats.default_stand(conn, project)
    if not stand:
        return {}
    run_id = stats.latest_finished_run_id(conn, project, stand)
    if not run_id:
        return {}
    entries = allure_report.parse_results(_allure_dir(run_id))
    return {entry["name"]: _bucket_status(entry) for entry in entries}


# ------------------------------------------------------------------ чтение


def _attachment_payload(row: sqlite3.Row, project: str) -> dict:
    return {
        "id": row["id"],
        "step_n": row["step_n"],
        "url": _attachment_url(project, row["case_id"], row["id"]),
        "source": row["source"],
        "created_at": row["created_at"],
    }


def _load_attachments(conn: sqlite3.Connection, project: str, case_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM test_case_attachments WHERE case_id = ? ORDER BY step_n, id", (case_id,)
    ).fetchall()
    return [_attachment_payload(row, project) for row in rows]


def _case_payload(row: sqlite3.Row, status: str | None, attachments: list[dict] | None = None) -> dict:
    """attachments=None — для list_tree/create_manual/update_case, где вложения
    не нужны в каждой строке дерева (N+1 запросов). get_case (карточка кейса)
    передаёт реальный список — по шагам (attachments[i]["step_n"] == steps[i]["n"])
    и общие (step_n == 0), см. описание модуля."""
    steps = json.loads(row["steps"] or "[]")
    by_step: dict[int, list[dict]] = {}
    for attachment in attachments or []:
        by_step.setdefault(attachment["step_n"], []).append(attachment)
    for step in steps:
        step["attachments"] = by_step.get(step["n"], [])
    return {
        "id": row["id"],
        "project": row["project"],
        "section": row["section"],
        "title": row["title"],
        "steps": steps,
        "precondition": row["precondition"],
        "requirement": row["requirement"],
        "priority": row["priority"],
        "nodeid": row["nodeid"],
        "source": row["source"],
        "updated_at": row["updated_at"],
        "updated_by": row["updated_by"],
        "status": status,
        "attachments": by_step.get(0, []),
    }


def get_case(conn: sqlite3.Connection, project: str, case_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM test_cases WHERE project = ? AND id = ?", (project, case_id)
    ).fetchone()
    if row is None:
        return None
    status = None
    if row["nodeid"]:
        status = _status_map(conn, project).get(_nodeid_to_full_name(row["nodeid"]))
    attachments = _load_attachments(conn, project, case_id)
    return _case_payload(row, status, attachments)


def _matches_query(row: sqlite3.Row, q: str) -> bool:
    steps = json.loads(row["steps"] or "[]")
    haystack = " ".join([row["title"]] + [s.get("action", "") + " " + s.get("expected", "") for s in steps])
    return q.lower() in haystack.lower()


def _build_tree(cases: list[dict]) -> dict:
    kinds: dict[str, dict] = {}
    for case in cases:
        section = case["section"] or "misc"
        kind, _, area = section.partition("/")
        kind_bucket = kinds.setdefault(kind, {"kind": kind, "areas": {}})
        area_bucket = kind_bucket["areas"].setdefault(area, {"area": area or None, "section": section, "cases": []})
        area_bucket["cases"].append(case)

    return {
        "kinds": [
            {"kind": kind, "areas": [kinds[kind]["areas"][a] for a in sorted(kinds[kind]["areas"])]}
            for kind in sorted(kinds)
        ]
    }


def list_tree(
    conn: sqlite3.Connection,
    project: str,
    section: str | None = None,
    status: str | None = None,
    has_test: bool | None = None,
    q: str | None = None,
) -> dict:
    rows = conn.execute(
        "SELECT * FROM test_cases WHERE project = ? ORDER BY section, title", (project,)
    ).fetchall()
    status_map = _status_map(conn, project)

    cases = []
    for row in rows:
        if section is not None and row["section"] != section:
            continue
        if has_test is True and not row["nodeid"]:
            continue
        if has_test is False and row["nodeid"]:
            continue
        case_status = status_map.get(_nodeid_to_full_name(row["nodeid"])) if row["nodeid"] else None
        if status is not None and (case_status or "none") != status:
            continue
        if q and not _matches_query(row, q):
            continue
        cases.append(_case_payload(row, case_status))

    return _build_tree(cases)


# ------------------------------------------------------------------ автосинхронизация со скриншотами allure


def _image_attachments_from_result(data: dict) -> list[tuple[int, str, str]]:
    """Один *-result.json -> [(step_n, имя_файла_в_results_dir, mime), ...] для
    image-вложений (см. описание модуля про step_n=0 и первый уровень steps[])."""
    found: list[tuple[int, str, str]] = []

    def _collect(attachments: list | None, step_n: int) -> None:
        for att in attachments or []:
            source = att.get("source")
            if not source:
                continue
            mime = att.get("type") or mimetypes.guess_type(att.get("name") or source)[0] or ""
            if mime in _IMAGE_MIME_EXTENSIONS:
                found.append((step_n, source, mime))

    _collect(data.get("attachments"), 0)
    for i, step in enumerate(data.get("steps") or [], start=1):
        _collect(step.get("attachments"), i)
    return found


def _attachments_by_full_name(results_dir: Path) -> dict[str, list[tuple[int, str, str]]]:
    by_full_name: dict[str, list[tuple[int, str, str]]] = {}
    for path in results_dir.glob("*-result.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        full_name = data.get("fullName") or data.get("name")
        if full_name:
            by_full_name[full_name] = _image_attachments_from_result(data)
    return by_full_name


def _clear_allure_attachments(conn: sqlite3.Connection, case_id: int) -> None:
    rows = conn.execute(
        "SELECT path FROM test_case_attachments WHERE case_id = ? AND source = 'allure'", (case_id,)
    ).fetchall()
    for row in rows:
        (TESTCASES_DIR / row["path"]).unlink(missing_ok=True)
    conn.execute("DELETE FROM test_case_attachments WHERE case_id = ? AND source = 'allure'", (case_id,))


def _replace_allure_attachments(
    conn: sqlite3.Connection,
    project: str,
    case_id: int,
    attachments: list[tuple[int, str, str]],
    results_dir: Path,
    now: str,
) -> None:
    _clear_allure_attachments(conn, case_id)
    if not attachments:
        return
    case_dir = attachments_dir(project, case_id)
    case_dir.mkdir(parents=True, exist_ok=True)
    for i, (step_n, source_name, mime) in enumerate(attachments):
        src = results_dir / source_name
        if not src.is_file():
            continue
        dest_name = f"allure_{step_n}_{i}{_IMAGE_MIME_EXTENSIONS[mime]}"
        (case_dir / dest_name).write_bytes(src.read_bytes())
        conn.execute(
            "INSERT INTO test_case_attachments (case_id, step_n, path, source, created_at) VALUES (?, ?, ?, 'allure', ?)",
            (case_id, step_n, f"{project}/{case_id}/{dest_name}", now),
        )


def sync_run_attachments(project: str, run_id: int) -> None:
    """Вызывается раннером после каждого завершённого прогона (см. описание
    модуля) — своя БД-коннекция, т.к. запускается через asyncio.to_thread из
    app.core.runner.py::_finalize, как и xfail_registry.recalc."""
    conn = get_connection()
    try:
        cases = conn.execute(
            "SELECT id, nodeid FROM test_cases WHERE project = ? AND nodeid IS NOT NULL AND nodeid != ''",
            (project,),
        ).fetchall()
        if not cases:
            return
        results_dir = settings.ALLURE_RESULTS_DIR / str(run_id)
        by_full_name = _attachments_by_full_name(results_dir)
        if not by_full_name:
            return
        now = datetime.now().isoformat(timespec="seconds")
        for case in cases:
            full_name = _nodeid_to_full_name(case["nodeid"])
            if full_name not in by_full_name:
                continue
            _replace_allure_attachments(conn, project, case["id"], by_full_name[full_name], results_dir, now)
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------ ручная загрузка/удаление вложений


def add_manual_attachment(
    conn: sqlite3.Connection, project: str, case_id: int, step_n: int, filename: str, data: bytes
) -> dict | None:
    """Сохраняет ручной скриншот шага (source='manual'). None — кейса с таким id
    в проекте нет; UnsupportedAttachmentType — расширение файла не png/jpg/jpeg."""
    case = conn.execute("SELECT id FROM test_cases WHERE project = ? AND id = ?", (project, case_id)).fetchone()
    if case is None:
        return None
    mime = _EXTENSION_MIME_TYPES.get(Path(filename).suffix.lower())
    if mime is None:
        raise UnsupportedAttachmentType(filename)

    case_dir = attachments_dir(project, case_id)
    case_dir.mkdir(parents=True, exist_ok=True)
    dest_name = f"manual_{uuid.uuid4().hex}{_IMAGE_MIME_EXTENSIONS[mime]}"
    (case_dir / dest_name).write_bytes(data)

    now = datetime.now().isoformat(timespec="seconds")
    rel_path = f"{project}/{case_id}/{dest_name}"
    cur = conn.execute(
        "INSERT INTO test_case_attachments (case_id, step_n, path, source, created_at) VALUES (?, ?, ?, 'manual', ?)",
        (case_id, step_n, rel_path, now),
    )
    conn.commit()
    return _attachment_payload(
        conn.execute("SELECT * FROM test_case_attachments WHERE id = ?", (cur.lastrowid,)).fetchone(), project
    )


def delete_manual_attachment(conn: sqlite3.Connection, project: str, case_id: int, attachment_id: int) -> bool:
    """True — удалено; False — не найдено (или кейс/проект не совпали);
    NotManualAttachment — найдено, но source='allure' (не годится для DELETE)."""
    row = conn.execute(
        "SELECT a.* FROM test_case_attachments a JOIN test_cases c ON c.id = a.case_id "
        "WHERE a.id = ? AND a.case_id = ? AND c.project = ?",
        (attachment_id, case_id, project),
    ).fetchone()
    if row is None:
        return False
    if row["source"] != "manual":
        raise NotManualAttachment(attachment_id)
    (TESTCASES_DIR / row["path"]).unlink(missing_ok=True)
    conn.execute("DELETE FROM test_case_attachments WHERE id = ?", (attachment_id,))
    conn.commit()
    return True


def get_attachment_file(conn: sqlite3.Connection, project: str, case_id: int, attachment_id: int) -> tuple[bytes, str] | None:
    """(содержимое, mime) вложения для отдачи GET .../attachments/{id}; None — не найдено."""
    row = conn.execute(
        "SELECT a.* FROM test_case_attachments a JOIN test_cases c ON c.id = a.case_id "
        "WHERE a.id = ? AND a.case_id = ? AND c.project = ?",
        (attachment_id, case_id, project),
    ).fetchone()
    if row is None:
        return None
    path = TESTCASES_DIR / row["path"]
    if not path.is_file():
        return None
    mime = _EXTENSION_MIME_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return path.read_bytes(), mime
