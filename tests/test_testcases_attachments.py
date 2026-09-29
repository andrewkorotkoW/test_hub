"""Скриншоты тест-кейсов (app/core/test_cases.py, app/routers/test_cases.py):
ручная загрузка/удаление через API (лимит размера, тип файла, права qa) и
автосинхронизация source='allure' после прогона (app.core.runner.py::_finalize
-> test_cases.sync_run_attachments) на фикстурных allure-results.

test_cases.TESTCASES_DIR вычисляется один раз при импорте модуля
(settings.WORKSPACE_DIR / "testcases", см. app/core/test_cases.py:61) — как и
app.core.stats.STATS_DIR, monkeypatch.setattr(settings, "WORKSPACE_DIR", ...)
его не подменит. Изолируем так же, как tests/test_stats.py изолирует
STATS_DIR: monkeypatch.setattr(test_cases, "TESTCASES_DIR", ...) напрямую."""
import json

import pytest

from app.core import test_cases
from app.db import get_connection

PROJECT = "tc_attach_proj"
STAND = "stage"

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-but-good-enough-for-extension-only-check"


@pytest.fixture()
def isolated_testcases_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(test_cases, "TESTCASES_DIR", tmp_path / "testcases_store")
    return tmp_path / "testcases_store"


@pytest.fixture()
def tc_project_dir(tmp_path):
    proj = tmp_path / "tc_attach_src_proj"
    proj.mkdir()
    return proj


def _insert_project(conn, path):
    conn.execute(
        "INSERT INTO projects (name, path, venv, stands) VALUES (?, ?, '.venv', '[]')",
        (PROJECT, str(path)),
    )
    conn.commit()


def _create_case(conn, nodeid=None, title="Кейс", section="api/auth", steps=None):
    return test_cases.create_manual(
        conn, PROJECT, section, title, None, "medium",
        steps or [{"action": "шаг 1", "expected": "результат 1"}, {"action": "шаг 2", "expected": "результат 2"}],
        nodeid, "qa",
    )


# ------------------------------------------------------------------ ручная загрузка/удаление через API

async def test_upload_manual_attachment_success(qa_client, db_path, isolated_testcases_dir, tc_project_dir):
    conn = get_connection()
    try:
        _insert_project(conn, tc_project_dir)
        case = _create_case(conn)
    finally:
        conn.close()

    resp = await qa_client.post(
        f"/api/projects/{PROJECT}/testcases/{case['id']}/steps/1/attachments",
        files={"file": ("shot.png", _PNG_BYTES, "image/png")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["step_n"] == 1
    assert body["source"] == "manual"

    card = (await qa_client.get(f"/api/projects/{PROJECT}/testcases/{case['id']}")).json()
    assert card["steps"][0]["attachments"][0]["id"] == body["id"]

    file_resp = await qa_client.get(body["url"])
    assert file_resp.status_code == 200
    assert file_resp.content == _PNG_BYTES


async def test_upload_step_zero_is_case_level_attachment(qa_client, db_path, isolated_testcases_dir, tc_project_dir):
    conn = get_connection()
    try:
        _insert_project(conn, tc_project_dir)
        case = _create_case(conn)
    finally:
        conn.close()

    resp = await qa_client.post(
        f"/api/projects/{PROJECT}/testcases/{case['id']}/steps/0/attachments",
        files={"file": ("shot.png", _PNG_BYTES, "image/png")},
    )
    assert resp.status_code == 201, resp.text

    card = (await qa_client.get(f"/api/projects/{PROJECT}/testcases/{case['id']}")).json()
    assert len(card["attachments"]) == 1
    assert card["steps"][0]["attachments"] == []


async def test_upload_rejects_oversized_file(qa_client, db_path, monkeypatch, isolated_testcases_dir, tc_project_dir):
    from app.config import settings

    monkeypatch.setattr(settings, "TH_TESTCASE_ATTACHMENT_MAX_BYTES", 10)
    conn = get_connection()
    try:
        _insert_project(conn, tc_project_dir)
        case = _create_case(conn)
    finally:
        conn.close()

    resp = await qa_client.post(
        f"/api/projects/{PROJECT}/testcases/{case['id']}/steps/1/attachments",
        files={"file": ("shot.png", _PNG_BYTES, "image/png")},
    )
    assert resp.status_code == 413, resp.text
    card = (await qa_client.get(f"/api/projects/{PROJECT}/testcases/{case['id']}")).json()
    assert card["steps"][0]["attachments"] == []


async def test_upload_rejects_unsupported_file_type(qa_client, db_path, isolated_testcases_dir, tc_project_dir):
    conn = get_connection()
    try:
        _insert_project(conn, tc_project_dir)
        case = _create_case(conn)
    finally:
        conn.close()

    resp = await qa_client.post(
        f"/api/projects/{PROJECT}/testcases/{case['id']}/steps/1/attachments",
        files={"file": ("notes.txt", b"just text", "text/plain")},
    )
    assert resp.status_code == 422, resp.text
    card = (await qa_client.get(f"/api/projects/{PROJECT}/testcases/{case['id']}")).json()
    assert card["steps"][0]["attachments"] == []


async def test_upload_requires_qa(manager_client, customer_client, db_path, isolated_testcases_dir, tc_project_dir):
    conn = get_connection()
    try:
        _insert_project(conn, tc_project_dir)
        case = _create_case(conn)
    finally:
        conn.close()

    resp_manager = await manager_client.post(
        f"/api/projects/{PROJECT}/testcases/{case['id']}/steps/1/attachments",
        files={"file": ("shot.png", _PNG_BYTES, "image/png")},
    )
    assert resp_manager.status_code == 403

    resp_customer = await customer_client.post(
        f"/api/projects/{PROJECT}/testcases/{case['id']}/steps/1/attachments",
        files={"file": ("shot.png", _PNG_BYTES, "image/png")},
    )
    assert resp_customer.status_code == 403


async def test_delete_manual_attachment_success(qa_client, db_path, isolated_testcases_dir, tc_project_dir):
    conn = get_connection()
    try:
        _insert_project(conn, tc_project_dir)
        case = _create_case(conn)
    finally:
        conn.close()

    upload_resp = await qa_client.post(
        f"/api/projects/{PROJECT}/testcases/{case['id']}/steps/1/attachments",
        files={"file": ("shot.png", _PNG_BYTES, "image/png")},
    )
    attachment_id = upload_resp.json()["id"]
    stored_path = isolated_testcases_dir / f"{PROJECT}" / str(case["id"])
    assert any(stored_path.iterdir())

    delete_resp = await qa_client.delete(f"/api/projects/{PROJECT}/testcases/{case['id']}/attachments/{attachment_id}")
    assert delete_resp.status_code == 204

    card = (await qa_client.get(f"/api/projects/{PROJECT}/testcases/{case['id']}")).json()
    assert card["steps"][0]["attachments"] == []
    assert not any(stored_path.iterdir())


def _insert_manual_attachment_row(conn, case_id, step_n=1):
    cur = conn.execute(
        "INSERT INTO test_case_attachments (case_id, step_n, path, source, created_at) VALUES (?, ?, 'x/manual.png', 'manual', '2024-01-01T00:00:00')",
        (case_id, step_n),
    )
    conn.commit()
    return cur.lastrowid


async def test_delete_requires_qa_forbidden_for_manager(manager_client, db_path, isolated_testcases_dir, tc_project_dir):
    # manager_client/customer_client используются в отдельных тестах, а не вместе:
    # обе фикстуры логинятся на общей AsyncClient (см. tests/test_xfail.py) — второй
    # login() в одном тесте затёр бы cookie первого.
    conn = get_connection()
    try:
        _insert_project(conn, tc_project_dir)
        case = _create_case(conn)
        attachment_id = _insert_manual_attachment_row(conn, case["id"])
    finally:
        conn.close()
    resp = await manager_client.delete(f"/api/projects/{PROJECT}/testcases/{case['id']}/attachments/{attachment_id}")
    assert resp.status_code == 403


async def test_delete_requires_qa_forbidden_for_customer(customer_client, db_path, isolated_testcases_dir, tc_project_dir):
    conn = get_connection()
    try:
        _insert_project(conn, tc_project_dir)
        case = _create_case(conn)
        attachment_id = _insert_manual_attachment_row(conn, case["id"])
    finally:
        conn.close()
    resp = await customer_client.delete(f"/api/projects/{PROJECT}/testcases/{case['id']}/attachments/{attachment_id}")
    assert resp.status_code == 403


async def test_delete_nonexistent_attachment_404(qa_client, db_path, isolated_testcases_dir, tc_project_dir):
    conn = get_connection()
    try:
        _insert_project(conn, tc_project_dir)
        case = _create_case(conn)
    finally:
        conn.close()
    resp = await qa_client.delete(f"/api/projects/{PROJECT}/testcases/{case['id']}/attachments/999999")
    assert resp.status_code == 404


async def test_delete_allure_attachment_via_api_is_forbidden(qa_client, db_path, isolated_testcases_dir, tc_project_dir):
    conn = get_connection()
    try:
        _insert_project(conn, tc_project_dir)
        case = _create_case(conn, nodeid="tests/api/auth/test_login.py::test_ok")
        case_dir = test_cases.attachments_dir(PROJECT, case["id"])
        case_dir.mkdir(parents=True)
        (case_dir / "allure_1_0.png").write_bytes(_PNG_BYTES)
        cur = conn.execute(
            "INSERT INTO test_case_attachments (case_id, step_n, path, source, created_at) VALUES (?, 1, ?, 'allure', '2024-01-01T00:00:00')",
            (case["id"], f"{PROJECT}/{case['id']}/allure_1_0.png"),
        )
        conn.commit()
        attachment_id = cur.lastrowid
    finally:
        conn.close()

    resp = await qa_client.delete(f"/api/projects/{PROJECT}/testcases/{case['id']}/attachments/{attachment_id}")
    assert resp.status_code == 403, resp.text

    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM test_case_attachments WHERE id = ?", (attachment_id,)).fetchone()
        assert row is not None  # не удалено
    finally:
        conn.close()


# ------------------------------------------------------------------ автосинхронизация allure-скриншотов после прогона

def _write_result_with_attachments(results_dir, filename, full_name, top_level, steps):
    results_dir.mkdir(parents=True, exist_ok=True)
    payload = {"fullName": full_name, "status": "passed", "attachments": top_level, "steps": steps}
    (results_dir / filename).write_text(json.dumps(payload), encoding="utf-8")


def _att(name, source, mime="image/png"):
    return {"name": name, "source": source, "type": mime}


def test_sync_run_attachments_copies_step_and_case_level_images(db_path, isolated_allure_dir, isolated_testcases_dir):
    from app.config import settings

    conn = get_connection()
    try:
        conn.execute("INSERT INTO projects (name, path, venv, stands) VALUES (?, '/tmp/x', '.venv', '[]')", (PROJECT,))
        case = _create_case(conn, nodeid="tests/api/auth/test_login.py::test_ok")
    finally:
        conn.close()

    run_id = 1
    results_dir = settings.ALLURE_RESULTS_DIR / str(run_id)
    results_dir.mkdir(parents=True)
    (results_dir / "case-level.png").write_bytes(b"case-level-bytes")
    (results_dir / "step1.png").write_bytes(b"step1-bytes")
    _write_result_with_attachments(
        results_dir, "00-result.json", "tests.api.auth.test_login#test_ok",
        top_level=[_att("overall", "case-level.png")],
        steps=[
            {"name": "шаг 1", "attachments": [_att("shot", "step1.png")]},
            {"name": "шаг 2", "attachments": []},
        ],
    )

    test_cases.sync_run_attachments(PROJECT, run_id)

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM test_case_attachments WHERE case_id = ? ORDER BY step_n", (case["id"],)
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 2
    by_step = {r["step_n"]: r for r in rows}
    assert by_step[0]["source"] == "allure"
    assert by_step[1]["source"] == "allure"
    assert (test_cases.TESTCASES_DIR / by_step[0]["path"]).read_bytes() == b"case-level-bytes"
    assert (test_cases.TESTCASES_DIR / by_step[1]["path"]).read_bytes() == b"step1-bytes"


def test_sync_run_attachments_replaces_not_accumulates(db_path, isolated_allure_dir, isolated_testcases_dir):
    from app.config import settings

    conn = get_connection()
    try:
        conn.execute("INSERT INTO projects (name, path, venv, stands) VALUES (?, '/tmp/x', '.venv', '[]')", (PROJECT,))
        case = _create_case(conn, nodeid="tests/api/auth/test_login.py::test_ok")
    finally:
        conn.close()

    run_a = 1
    results_dir_a = settings.ALLURE_RESULTS_DIR / str(run_a)
    results_dir_a.mkdir(parents=True)
    (results_dir_a / "first.png").write_bytes(b"first-run-bytes")
    _write_result_with_attachments(
        results_dir_a, "00-result.json", "tests.api.auth.test_login#test_ok",
        top_level=[], steps=[{"name": "шаг 1", "attachments": [_att("shot", "first.png")]}],
    )
    test_cases.sync_run_attachments(PROJECT, run_a)

    conn = get_connection()
    try:
        first_rows = conn.execute(
            "SELECT * FROM test_case_attachments WHERE case_id = ? AND source = 'allure'", (case["id"],)
        ).fetchall()
    finally:
        conn.close()
    assert len(first_rows) == 1
    first_path = test_cases.TESTCASES_DIR / first_rows[0]["path"]
    assert first_path.is_file()

    # Второй прогон кладёт вложение на другую позицию (шаг 2, а не шаг 1) — это
    # проверяет, что старый файл действительно удаляется с диска, а не просто
    # перезаписывается по совпавшему имени allure_<step_n>_<i>.<ext>.
    run_b = 2
    results_dir_b = settings.ALLURE_RESULTS_DIR / str(run_b)
    results_dir_b.mkdir(parents=True)
    (results_dir_b / "second.png").write_bytes(b"second-run-bytes")
    _write_result_with_attachments(
        results_dir_b, "00-result.json", "tests.api.auth.test_login#test_ok",
        top_level=[],
        steps=[{"name": "шаг 1", "attachments": []}, {"name": "шаг 2", "attachments": [_att("shot", "second.png")]}],
    )
    test_cases.sync_run_attachments(PROJECT, run_b)

    conn = get_connection()
    try:
        second_rows = conn.execute(
            "SELECT * FROM test_case_attachments WHERE case_id = ? AND source = 'allure'", (case["id"],)
        ).fetchall()
    finally:
        conn.close()
    assert len(second_rows) == 1  # заменено, не накоплено
    assert (test_cases.TESTCASES_DIR / second_rows[0]["path"]).read_bytes() == b"second-run-bytes"
    assert not first_path.is_file()  # старый файл прошлого прогона удалён с диска


def test_sync_run_attachments_preserves_manual_and_untouched_cases(db_path, isolated_allure_dir, isolated_testcases_dir):
    from app.config import settings

    conn = get_connection()
    try:
        conn.execute("INSERT INTO projects (name, path, venv, stands) VALUES (?, '/tmp/x', '.venv', '[]')", (PROJECT,))
        case_ran = _create_case(conn, nodeid="tests/api/auth/test_login.py::test_ok", title="Прогнан")
        case_not_ran = _create_case(conn, nodeid="tests/api/auth/test_login.py::test_other", title="Не в этом прогоне")
        conn.execute(
            "INSERT INTO test_case_attachments (case_id, step_n, path, source, created_at) VALUES (?, 1, 'manual/manual.png', 'manual', '2024-01-01T00:00:00')",
            (case_ran["id"],),
        )
        conn.execute(
            "INSERT INTO test_case_attachments (case_id, step_n, path, source, created_at) VALUES (?, 1, 'old/old.png', 'allure', '2024-01-01T00:00:00')",
            (case_not_ran["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    run_id = 1
    results_dir = settings.ALLURE_RESULTS_DIR / str(run_id)
    results_dir.mkdir(parents=True)
    (results_dir / "new.png").write_bytes(b"new-bytes")
    _write_result_with_attachments(
        results_dir, "00-result.json", "tests.api.auth.test_login#test_ok",
        top_level=[], steps=[{"name": "шаг 1", "attachments": [_att("shot", "new.png")]}],
    )
    test_cases.sync_run_attachments(PROJECT, run_id)

    conn = get_connection()
    try:
        ran_rows = conn.execute("SELECT * FROM test_case_attachments WHERE case_id = ?", (case_ran["id"],)).fetchall()
        not_ran_rows = conn.execute(
            "SELECT * FROM test_case_attachments WHERE case_id = ?", (case_not_ran["id"],)
        ).fetchall()
    finally:
        conn.close()

    sources = {r["source"] for r in ran_rows}
    assert sources == {"manual", "allure"}  # ручное вложение не тронуто автосинком
    assert len(not_ran_rows) == 1
    assert not_ran_rows[0]["source"] == "allure"
    assert not_ran_rows[0]["path"] == "old/old.png"  # тест не участвовал в прогоне -> старые скриншоты остались


def test_sync_run_attachments_ignores_non_image_attachments(db_path, isolated_allure_dir, isolated_testcases_dir):
    from app.config import settings

    conn = get_connection()
    try:
        conn.execute("INSERT INTO projects (name, path, venv, stands) VALUES (?, '/tmp/x', '.venv', '[]')", (PROJECT,))
        case = _create_case(conn, nodeid="tests/api/auth/test_login.py::test_ok")
    finally:
        conn.close()

    run_id = 1
    results_dir = settings.ALLURE_RESULTS_DIR / str(run_id)
    results_dir.mkdir(parents=True)
    (results_dir / "log.txt").write_bytes(b"text log, not an image")
    _write_result_with_attachments(
        results_dir, "00-result.json", "tests.api.auth.test_login#test_ok",
        top_level=[_att("log", "log.txt", mime="text/plain")], steps=[],
    )
    test_cases.sync_run_attachments(PROJECT, run_id)

    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM test_case_attachments WHERE case_id = ?", (case["id"],)).fetchall()
    finally:
        conn.close()
    assert rows == []


def test_sync_run_attachments_noop_for_cases_without_nodeid(db_path, isolated_allure_dir, isolated_testcases_dir):
    from app.config import settings

    conn = get_connection()
    try:
        conn.execute("INSERT INTO projects (name, path, venv, stands) VALUES (?, '/tmp/x', '.venv', '[]')", (PROJECT,))
        _create_case(conn, nodeid=None, title="Ручной без автотеста")
    finally:
        conn.close()

    run_id = 1
    results_dir = settings.ALLURE_RESULTS_DIR / str(run_id)
    results_dir.mkdir(parents=True)
    # sync_run_attachments не должен падать, даже если у проекта нет кейсов с nodeid
    test_cases.sync_run_attachments(PROJECT, run_id)
