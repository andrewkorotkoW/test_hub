"""Импорт черновиков `docs/test_cases/**/*.md` (app/core/test_cases.py::parse_area_file/
import_drafts) — портированный парсер из auto_tests_vshgu (см. описание модуля).
Фикстурный markdown ниже НЕ дёргает реальный auto_tests_vshgu_cloude, а
воспроизводит формат черновика по регэкспам app/core/test_cases.py (HEADING_RE/
AUTOTEST_RE/META_RE/PRECONDITION_RE/REQUIREMENT_RE + таблица шагов)."""
import json
import sqlite3

import pytest

from app.core import test_cases
from app.db import get_connection

PROJECT = "tc_import_proj"

_AREA_MD = """\
### TC-API-1 Успешный логин

- Автотест: tests/api/auth/test_login.py::test_login_success
- Приоритет: high Тип: functional Роли: qa, manager
- Предусловия: пользователь зарегистрирован в системе

| № | Действие | Ожидаемый результат |
| --- | --- | --- |
| 1 | Открыть страницу логина | Страница логина отображается |
| 2 | Ввести верный логин и пароль | Пользователь авторизован, виден дашборд |

### TC-API-2 Логин с неверным паролем

- Автотест: tests/api/auth/test_login.py::test_login_wrong_password
- Приоритет: medium Тип: functional Роли: qa

| № | Действие | Ожидаемый результат |
| --- | --- | --- |
| 1 | Открыть страницу логина | Страница логина отображается |
| 2 | Ввести неверный пароль | Показана ошибка авторизации |

### TC-API-3 Ручной кейс без автотеста

- Приоритет: low Тип: manual Роли: qa

| № | Действие | Ожидаемый результат |
| --- | --- | --- |
| 1 | Проверить руками | Всё хорошо |
"""

_UPDATED_AREA_MD = """\
### TC-API-1 Успешный логин (обновлено)

- Автотест: tests/api/auth/test_login.py::test_login_success
- Приоритет: high Тип: functional Роли: qa, manager
- Предусловия: пользователь зарегистрирован и подтверждён

| № | Действие | Ожидаемый результат |
| --- | --- | --- |
| 1 | Открыть страницу логина | Страница логина отображается |
| 2 | Ввести верный логин и пароль | Пользователь авторизован |
| 3 | Проверить приветствие | Показано имя пользователя |
"""


_SUBDIR_MD = """\
### TC-MTS-1 Создание связи

- Автотест: tests/api/mts_link/test_create.py::test_ok
- Приоритет: high Тип: functional Роли: qa
- Требование: REQ-42 создание связи МТС

| № | Действие | Ожидаемый результат |
| --- | --- | --- |
| 1 | Отправить запрос на создание | Связь создана |

### TC-MTS-2 Ручной кейс без автотеста

- Приоритет: medium Тип: manual Роли: qa
- Требование: REQ-43 ручная проверка

| № | Действие | Ожидаемый результат |
| --- | --- | --- |
| 1 | Проверить руками | Всё хорошо |
"""


@pytest.fixture()
def vshgu_like_project_dir(tmp_path):
    proj = tmp_path / "vshgu_like_proj"
    docs_dir = proj / "docs" / "test_cases"
    docs_dir.mkdir(parents=True)
    (docs_dir / "api_auth.md").write_text(_AREA_MD, encoding="utf-8")
    (docs_dir / "TEMPLATE.md").write_text("### TC-XXX-0 Шаблон\n\n- Приоритет: low Тип: x Роли: qa\n", encoding="utf-8")
    return proj


@pytest.fixture()
def vshgu_like_project_with_subdir(tmp_path):
    proj = tmp_path / "vshgu_like_subdir_proj"
    docs_dir = proj / "docs" / "test_cases"
    subdir = docs_dir / "mts_link"
    subdir.mkdir(parents=True)
    (docs_dir / "api_auth.md").write_text(_AREA_MD, encoding="utf-8")
    (subdir / "02_create.md").write_text(_SUBDIR_MD, encoding="utf-8")
    (subdir / "TEMPLATE.md").write_text("### TC-XXX-0 Шаблон\n\n- Приоритет: low Тип: x Роли: qa\n", encoding="utf-8")
    return proj


def _insert_project(conn, path):
    conn.execute(
        "INSERT INTO projects (name, path, venv, stands) VALUES (?, ?, '.venv', '[]')",
        (PROJECT, str(path)),
    )
    conn.commit()


# ------------------------------------------------------------------ parse_area_file() напрямую

def test_parse_area_file_extracts_cases_with_and_without_nodeid(vshgu_like_project_dir):
    cases = test_cases.parse_area_file(vshgu_like_project_dir / "docs" / "test_cases" / "api_auth.md")
    assert [c["title"] for c in cases] == [
        "Успешный логин",
        "Логин с неверным паролем",
        "Ручной кейс без автотеста",
    ]
    first = cases[0]
    assert first["nodeid"] == "tests/api/auth/test_login.py::test_login_success"
    assert first["priority"] == "high"
    assert first["precondition"] == "пользователь зарегистрирован в системе"
    assert first["steps"] == [
        {"action": "Открыть страницу логина", "expected": "Страница логина отображается"},
        {"action": "Ввести верный логин и пароль", "expected": "Пользователь авторизован, виден дашборд"},
    ]
    assert first["case_id"] == "TC-API-1"
    assert first["requirement"] is None
    manual_like = cases[2]
    assert manual_like["nodeid"] is None
    assert manual_like["precondition"] is None
    assert manual_like["case_id"] == "TC-API-3"


def test_parse_area_file_parses_requirement_line(tmp_path):
    md = tmp_path / "req.md"
    md.write_text(
        "### TC-REQ-1 Кейс с требованием\n\n"
        "- Требование: REQ-100 нечто важное\n\n"
        "| № | Действие | Ожидаемый результат |\n"
        "| --- | --- | --- |\n"
        "| 1 | Шаг | Результат |\n",
        encoding="utf-8",
    )
    cases = test_cases.parse_area_file(md)
    assert cases[0]["requirement"] == "REQ-100 нечто важное"
    assert cases[0]["case_id"] == "TC-REQ-1"


# ------------------------------------------------------------------ import_drafts(): upsert по (project, case_key)

def test_import_drafts_imports_manual_cases_without_nodeid_too(db_path, vshgu_like_project_dir):
    conn = get_connection()
    try:
        _insert_project(conn, vshgu_like_project_dir)
        project_row = conn.execute("SELECT * FROM projects WHERE name = ?", (PROJECT,)).fetchone()
        result = test_cases.import_drafts(conn, project_row)
        assert result == {"files": 1, "imported": 3, "updated": 0, "skipped_manual": 0}

        rows = conn.execute("SELECT * FROM test_cases WHERE project = ?", (PROJECT,)).fetchall()
        assert len(rows) == 3  # TC-API-3 без Автотест: теперь тоже импортируется как ручной
        with_test = {r["nodeid"]: r for r in rows if r["nodeid"]}
        row = with_test["tests/api/auth/test_login.py::test_login_success"]
        assert row["source"] == "generated"
        assert row["section"] == "api/auth"
        assert row["case_key"] == row["nodeid"]
        steps = json.loads(row["steps"])
        assert steps[0] == {"n": 1, "action": "Открыть страницу логина", "expected": "Страница логина отображается", "attachments": []}

        manual_row = next(r for r in rows if r["nodeid"] is None)
        assert manual_row["source"] == "generated"
        assert manual_row["case_key"] == "TC-API-3"
        assert manual_row["title"] == "Ручной кейс без автотеста"
        assert manual_row["section"] == "api_auth"  # раздел без nodeid — имя файла-черновика
    finally:
        conn.close()


def test_import_drafts_manual_case_updates_then_respects_manual_edit(db_path, vshgu_like_project_dir):
    conn = get_connection()
    try:
        _insert_project(conn, vshgu_like_project_dir)
        project_row = conn.execute("SELECT * FROM projects WHERE name = ?", (PROJECT,)).fetchone()
        test_cases.import_drafts(conn, project_row)
        case_row = conn.execute(
            "SELECT * FROM test_cases WHERE project = ? AND case_key = ?", (PROJECT, "TC-API-3")
        ).fetchone()
        assert case_row["nodeid"] is None
        assert case_row["source"] == "generated"

        updated_md = _AREA_MD.replace(
            "### TC-API-3 Ручной кейс без автотеста",
            "### TC-API-3 Ручной кейс без автотеста (обновлено)",
        )
        (vshgu_like_project_dir / "docs" / "test_cases" / "api_auth.md").write_text(updated_md, encoding="utf-8")
        result = test_cases.import_drafts(conn, project_row)
        # все 3 кейса файла уже существуют (generated) -> все 3 обновляются повторным импортом
        assert result == {"files": 1, "imported": 0, "updated": 3, "skipped_manual": 0}
        row = conn.execute("SELECT * FROM test_cases WHERE id = ?", (case_row["id"],)).fetchone()
        assert row["title"] == "Ручной кейс без автотеста (обновлено)"

        # ручная правка через update_case -> source='manual', повторный импорт не затирает
        test_cases.update_case(
            conn, row["id"], "Кейс, изменённый руками", None, "low",
            [{"action": "шаг руками", "expected": "результат руками"}], None, "qa",
        )
        (vshgu_like_project_dir / "docs" / "test_cases" / "api_auth.md").write_text(_AREA_MD, encoding="utf-8")
        result2 = test_cases.import_drafts(conn, project_row)
        assert result2 == {"files": 1, "imported": 0, "updated": 2, "skipped_manual": 1}
        final_row = conn.execute("SELECT * FROM test_cases WHERE id = ?", (row["id"],)).fetchone()
        assert final_row["title"] == "Кейс, изменённый руками"
        assert final_row["source"] == "manual"
    finally:
        conn.close()


def test_case_key_unique_per_project(db_path, vshgu_like_project_dir):
    conn = get_connection()
    try:
        _insert_project(conn, vshgu_like_project_dir)
        project_row = conn.execute("SELECT * FROM projects WHERE name = ?", (PROJECT,)).fetchone()
        test_cases.import_drafts(conn, project_row)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO test_cases (project, section, title, steps, priority, case_key, source, updated_at) "
                "VALUES (?, 'x', 'dup', '[]', 'medium', 'TC-API-3', 'generated', '2024-01-01')",
                (PROJECT,),
            )
    finally:
        conn.close()


# ------------------------------------------------------------------ import_drafts(): рекурсия по подпапкам

def test_import_drafts_recursive_subdir_sections_and_requirement(db_path, vshgu_like_project_with_subdir):
    conn = get_connection()
    try:
        _insert_project(conn, vshgu_like_project_with_subdir)
        project_row = conn.execute("SELECT * FROM projects WHERE name = ?", (PROJECT,)).fetchone()
        result = test_cases.import_drafts(conn, project_row)
        assert result["files"] == 2  # api_auth.md + mts_link/02_create.md (TEMPLATE.md в подпапке пропущен)
        assert result["imported"] == 5  # 3 из api_auth.md + 2 из mts_link/02_create.md

        with_test_row = conn.execute(
            "SELECT * FROM test_cases WHERE project = ? AND nodeid = ?",
            (PROJECT, "tests/api/mts_link/test_create.py::test_ok"),
        ).fetchone()
        assert with_test_row is not None
        assert with_test_row["section"] == "mts_link/api/mts_link"  # подпапка — верхний уровень секции
        assert with_test_row["case_key"] == "tests/api/mts_link/test_create.py::test_ok"
        assert with_test_row["requirement"] == "REQ-42 создание связи МТС"

        manual_row = conn.execute(
            "SELECT * FROM test_cases WHERE project = ? AND case_key = ?", (PROJECT, "TC-MTS-2")
        ).fetchone()
        assert manual_row is not None
        assert manual_row["nodeid"] is None
        assert manual_row["section"] == "mts_link/02_create"  # подпапка + имя файла без расширения
        assert manual_row["source"] == "generated"
        assert manual_row["requirement"] == "REQ-43 ручная проверка"
    finally:
        conn.close()


def test_import_drafts_ignores_template_file(db_path, vshgu_like_project_dir):
    conn = get_connection()
    try:
        _insert_project(conn, vshgu_like_project_dir)
        project_row = conn.execute("SELECT * FROM projects WHERE name = ?", (PROJECT,)).fetchone()
        result = test_cases.import_drafts(conn, project_row)
        assert result["files"] == 1  # TEMPLATE.md не считается
    finally:
        conn.close()


def test_import_drafts_on_missing_docs_dir_is_noop(db_path, tmp_path):
    conn = get_connection()
    try:
        empty_proj = tmp_path / "no_docs_proj"
        empty_proj.mkdir()
        _insert_project(conn, empty_proj)
        project_row = conn.execute("SELECT * FROM projects WHERE name = ?", (PROJECT,)).fetchone()
        result = test_cases.import_drafts(conn, project_row)
        assert result == {"files": 0, "imported": 0, "updated": 0, "skipped_manual": 0}
        assert conn.execute("SELECT COUNT(*) FROM test_cases WHERE project = ?", (PROJECT,)).fetchone()[0] == 0
    finally:
        conn.close()


def test_import_drafts_repeated_import_updates_generated_case_in_place(db_path, vshgu_like_project_dir):
    conn = get_connection()
    try:
        _insert_project(conn, vshgu_like_project_dir)
        project_row = conn.execute("SELECT * FROM projects WHERE name = ?", (PROJECT,)).fetchone()
        test_cases.import_drafts(conn, project_row)

        (vshgu_like_project_dir / "docs" / "test_cases" / "api_auth.md").write_text(_UPDATED_AREA_MD, encoding="utf-8")
        result = test_cases.import_drafts(conn, project_row)
        assert result == {"files": 1, "imported": 0, "updated": 1, "skipped_manual": 0}

        rows = conn.execute(
            "SELECT * FROM test_cases WHERE project = ? AND nodeid = ?",
            (PROJECT, "tests/api/auth/test_login.py::test_login_success"),
        ).fetchall()
        assert len(rows) == 1  # апсерт по (project, nodeid) — не новая строка, а обновление
        row = rows[0]
        assert row["title"] == "Успешный логин (обновлено)"
        assert row["precondition"] == "пользователь зарегистрирован и подтверждён"
        assert len(json.loads(row["steps"])) == 3
        assert row["source"] == "generated"
    finally:
        conn.close()


def test_import_drafts_does_not_overwrite_manual_case(db_path, vshgu_like_project_dir):
    conn = get_connection()
    try:
        _insert_project(conn, vshgu_like_project_dir)
        project_row = conn.execute("SELECT * FROM projects WHERE name = ?", (PROJECT,)).fetchone()
        test_cases.import_drafts(conn, project_row)

        case_row = conn.execute(
            "SELECT id FROM test_cases WHERE project = ? AND nodeid = ?",
            (PROJECT, "tests/api/auth/test_login.py::test_login_success"),
        ).fetchone()
        # qa вручную правит кейс -> source становится 'manual' (update_case)
        test_cases.update_case(
            conn, case_row["id"], "Название, изменённое руками", "новое предусловие", "high",
            [{"action": "шаг руками", "expected": "результат руками"}],
            "tests/api/auth/test_login.py::test_login_success", "qa",
        )

        (vshgu_like_project_dir / "docs" / "test_cases" / "api_auth.md").write_text(_UPDATED_AREA_MD, encoding="utf-8")
        result = test_cases.import_drafts(conn, project_row)
        assert result["skipped_manual"] == 1
        assert result["updated"] == 0

        row = conn.execute("SELECT * FROM test_cases WHERE id = ?", (case_row["id"],)).fetchone()
        assert row["title"] == "Название, изменённое руками"
        assert row["source"] == "manual"
        assert json.loads(row["steps"])[0]["action"] == "шаг руками"
    finally:
        conn.close()
