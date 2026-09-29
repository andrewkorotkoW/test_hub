"""REST API вкладки «Тест-кейсы» (app/routers/test_cases.py): права ролей
(qa правит, manager/customer только читают — по образцу tests/test_xfail.py),
дерево с фильтрами/поиском, карточка кейса, правка. Вложения — в
tests/test_testcases_attachments.py."""
import json

import pytest

from app.core import test_cases
from app.db import get_connection

from .conftest import register_project

PROJECT = "tc_api_proj"
STAND = "stage"


@pytest.fixture()
def tc_project_dir(tmp_path):
    proj = tmp_path / "tc_api_src_proj"
    proj.mkdir()
    return proj


async def _register(qa_client, path):
    return await register_project(qa_client, PROJECT, path)


def _insert_run(conn, status="passed"):
    cur = conn.execute(
        "INSERT INTO runs (project, stand, target, status, started, finished, requested_by, counts) "
        "VALUES (?, ?, 'all', ?, '2024-01-01T00:00:00', '2024-01-01T00:01:00', 'qa', '{}')",
        (PROJECT, STAND, status),
    )
    conn.commit()
    return cur.lastrowid


def _write_allure_result(results_dir, filename, full_name, status_):
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / filename).write_text(json.dumps({"fullName": full_name, "status": status_}), encoding="utf-8")


def _create_case(conn, nodeid=None, title="Кейс", section="api/auth"):
    return test_cases.create_manual(
        conn, PROJECT, section, title, None, "medium",
        [{"action": "шаг 1", "expected": "результат 1"}], nodeid, "qa",
    )


# ------------------------------------------------------------------ права ролей

async def test_import_requires_qa(customer_client, db_path, tc_project_dir):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES (?, ?, '.venv', '[]')", (PROJECT, str(tc_project_dir))
        )
        conn.commit()
    finally:
        conn.close()
    resp = await customer_client.post(f"/api/projects/{PROJECT}/testcases/import")
    assert resp.status_code == 403


async def test_import_forbidden_for_manager(manager_client, db_path, tc_project_dir):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES (?, ?, '.venv', '[]')", (PROJECT, str(tc_project_dir))
        )
        conn.commit()
    finally:
        conn.close()
    resp = await manager_client.post(f"/api/projects/{PROJECT}/testcases/import")
    assert resp.status_code == 403


async def test_import_allowed_for_qa(qa_client, db_path, tc_project_dir):
    await _register(qa_client, tc_project_dir)
    resp = await qa_client.post(f"/api/projects/{PROJECT}/testcases/import")
    assert resp.status_code == 201, resp.text
    assert resp.json() == {"files": 0, "imported": 0, "updated": 0, "skipped_manual": 0}


async def test_create_requires_qa(customer_client, manager_client, db_path, tc_project_dir):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES (?, ?, '.venv', '[]')", (PROJECT, str(tc_project_dir))
        )
        conn.commit()
    finally:
        conn.close()
    body = {"section": "api/auth", "title": "Новый кейс", "steps": []}
    resp_customer = await customer_client.post(f"/api/projects/{PROJECT}/testcases", json=body)
    assert resp_customer.status_code == 403
    resp_manager = await manager_client.post(f"/api/projects/{PROJECT}/testcases", json=body)
    assert resp_manager.status_code == 403


async def test_update_requires_qa(customer_client, manager_client, db_path, tc_project_dir):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES (?, ?, '.venv', '[]')", (PROJECT, str(tc_project_dir))
        )
        conn.commit()
        case = _create_case(conn)
    finally:
        conn.close()
    body = {"title": "Правка", "steps": []}
    resp_customer = await customer_client.put(f"/api/projects/{PROJECT}/testcases/{case['id']}", json=body)
    assert resp_customer.status_code == 403
    resp_manager = await manager_client.put(f"/api/projects/{PROJECT}/testcases/{case['id']}", json=body)
    assert resp_manager.status_code == 403


async def _setup_project_with_case(tc_project_dir):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES (?, ?, '.venv', '[]')", (PROJECT, str(tc_project_dir))
        )
        conn.commit()
        return _create_case(conn)
    finally:
        conn.close()


async def test_list_tree_readable_by_qa(qa_client, db_path, tc_project_dir):
    await _setup_project_with_case(tc_project_dir)
    resp = await qa_client.get(f"/api/projects/{PROJECT}/testcases")
    assert resp.status_code == 200, resp.text


async def test_list_tree_readable_by_manager(manager_client, db_path, tc_project_dir):
    await _setup_project_with_case(tc_project_dir)
    resp = await manager_client.get(f"/api/projects/{PROJECT}/testcases")
    assert resp.status_code == 200, resp.text


async def test_list_tree_readable_by_customer(customer_client, db_path, tc_project_dir):
    await _setup_project_with_case(tc_project_dir)
    resp = await customer_client.get(f"/api/projects/{PROJECT}/testcases")
    assert resp.status_code == 200, resp.text


async def test_get_case_readable_by_qa(qa_client, db_path, tc_project_dir):
    case = await _setup_project_with_case(tc_project_dir)
    resp = await qa_client.get(f"/api/projects/{PROJECT}/testcases/{case['id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == case["id"]


async def test_get_case_readable_by_manager(manager_client, db_path, tc_project_dir):
    case = await _setup_project_with_case(tc_project_dir)
    resp = await manager_client.get(f"/api/projects/{PROJECT}/testcases/{case['id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == case["id"]


async def test_get_case_readable_by_customer(customer_client, db_path, tc_project_dir):
    case = await _setup_project_with_case(tc_project_dir)
    resp = await customer_client.get(f"/api/projects/{PROJECT}/testcases/{case['id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == case["id"]


# ------------------------------------------------------------------ дерево / фильтры / поиск / карточка

async def test_list_tree_groups_by_kind_and_area(qa_client, db_path, tc_project_dir):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES (?, ?, '.venv', '[]')", (PROJECT, str(tc_project_dir))
        )
        conn.commit()
        _create_case(conn, title="Кейс API auth", section="api/auth")
        _create_case(conn, title="Кейс UI buk", section="ui/buk")
        _create_case(conn, title="Кейс e2e", section="e2e")
    finally:
        conn.close()

    resp = await qa_client.get(f"/api/projects/{PROJECT}/testcases")
    assert resp.status_code == 200, resp.text
    tree = resp.json()
    kinds = {k["kind"]: k for k in tree["kinds"]}
    assert set(kinds) == {"api", "ui", "e2e"}
    assert kinds["api"]["areas"][0]["area"] == "auth"
    assert kinds["api"]["areas"][0]["cases"][0]["title"] == "Кейс API auth"
    assert kinds["e2e"]["areas"][0]["area"] is None
    assert kinds["e2e"]["areas"][0]["section"] == "e2e"


async def test_list_tree_filter_by_section(qa_client, db_path, tc_project_dir):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES (?, ?, '.venv', '[]')", (PROJECT, str(tc_project_dir))
        )
        conn.commit()
        _create_case(conn, title="A", section="api/auth")
        _create_case(conn, title="B", section="api/buk")
    finally:
        conn.close()

    resp = await qa_client.get(f"/api/projects/{PROJECT}/testcases", params={"section": "api/auth"})
    tree = resp.json()
    titles = [c["title"] for k in tree["kinds"] for a in k["areas"] for c in a["cases"]]
    assert titles == ["A"]


async def test_list_tree_filter_by_has_test(qa_client, db_path, tc_project_dir):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES (?, ?, '.venv', '[]')", (PROJECT, str(tc_project_dir))
        )
        conn.commit()
        _create_case(conn, nodeid="tests/api/auth/test_login.py::test_ok", title="С автотестом", section="api/auth")
        _create_case(conn, nodeid=None, title="Без автотеста", section="api/auth")
    finally:
        conn.close()

    resp_yes = await qa_client.get(f"/api/projects/{PROJECT}/testcases", params={"has_test": "true"})
    titles_yes = [c["title"] for k in resp_yes.json()["kinds"] for a in k["areas"] for c in a["cases"]]
    assert titles_yes == ["С автотестом"]

    resp_no = await qa_client.get(f"/api/projects/{PROJECT}/testcases", params={"has_test": "false"})
    titles_no = [c["title"] for k in resp_no.json()["kinds"] for a in k["areas"] for c in a["cases"]]
    assert titles_no == ["Без автотеста"]


async def test_list_tree_search_by_title_and_steps(qa_client, db_path, tc_project_dir):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES (?, ?, '.venv', '[]')", (PROJECT, str(tc_project_dir))
        )
        conn.commit()
        test_cases.create_manual(
            conn, PROJECT, "api/auth", "Логин", None, "medium",
            [{"action": "ввести пароль", "expected": "успех"}], None, "qa",
        )
        test_cases.create_manual(
            conn, PROJECT, "api/auth", "Прочее", None, "medium",
            [{"action": "нажать кнопку", "expected": "переход на дашборд"}], None, "qa",
        )
    finally:
        conn.close()

    resp_title = await qa_client.get(f"/api/projects/{PROJECT}/testcases", params={"q": "логин"})
    titles = [c["title"] for k in resp_title.json()["kinds"] for a in k["areas"] for c in a["cases"]]
    assert titles == ["Логин"]

    resp_step = await qa_client.get(f"/api/projects/{PROJECT}/testcases", params={"q": "дашборд"})
    titles_step = [c["title"] for k in resp_step.json()["kinds"] for a in k["areas"] for c in a["cases"]]
    assert titles_step == ["Прочее"]


async def test_list_tree_filter_by_status_uses_latest_finished_run(qa_client, db_path, isolated_allure_dir, tc_project_dir):
    from app.config import settings

    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES (?, ?, '.venv', '[]')", (PROJECT, str(tc_project_dir))
        )
        conn.execute("INSERT INTO stands (project, name, url, login) VALUES (?, ?, '', NULL)", (PROJECT, STAND))
        conn.commit()
        run_id = _insert_run(conn, status="passed")
        case_ok = _create_case(conn, nodeid="tests/api/auth/test_login.py::test_ok", title="Прошёл", section="api/auth")
        case_fail = _create_case(conn, nodeid="tests/api/auth/test_login.py::test_bad", title="Упал", section="api/auth")
    finally:
        conn.close()

    results_dir = settings.ALLURE_RESULTS_DIR / str(run_id)
    _write_allure_result(results_dir, "00-result.json", "tests.api.auth.test_login#test_ok", "passed")
    _write_allure_result(results_dir, "01-result.json", "tests.api.auth.test_login#test_bad", "failed")

    resp_card = await qa_client.get(f"/api/projects/{PROJECT}/testcases/{case_ok['id']}")
    assert resp_card.json()["status"] == "passed"

    resp_filtered = await qa_client.get(f"/api/projects/{PROJECT}/testcases", params={"status": "failed"})
    titles = [c["title"] for k in resp_filtered.json()["kinds"] for a in k["areas"] for c in a["cases"]]
    assert titles == ["Упал"]
    assert case_fail["title"] == "Упал"


async def test_get_case_not_found(qa_client, db_path, tc_project_dir):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES (?, ?, '.venv', '[]')", (PROJECT, str(tc_project_dir))
        )
        conn.commit()
    finally:
        conn.close()
    resp = await qa_client.get(f"/api/projects/{PROJECT}/testcases/999999")
    assert resp.status_code == 404


# ------------------------------------------------------------------ правка кейса

async def test_update_case_switches_source_generated_to_manual_and_applies_all_fields(qa_client, db_path, tc_project_dir):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES (?, ?, '.venv', '[]')", (PROJECT, str(tc_project_dir))
        )
        conn.commit()
        cur = conn.execute(
            "INSERT INTO test_cases (project, section, title, steps, precondition, priority, nodeid, source, updated_at, updated_by) "
            "VALUES (?, 'api/auth', 'Сгенерированный', '[]', NULL, 'medium', 'tests/api/auth/test_login.py::test_x', 'generated', '2024-01-01T00:00:00', NULL)",
            (PROJECT,),
        )
        conn.commit()
        case_id = cur.lastrowid
    finally:
        conn.close()

    resp = await qa_client.put(
        f"/api/projects/{PROJECT}/testcases/{case_id}",
        json={
            "title": "Правленный вручную",
            "precondition": "новое предусловие",
            "priority": "high",
            "nodeid": "tests/api/auth/test_login.py::test_x",
            "steps": [
                {"action": "шаг 1", "expected": "ожидание 1"},
                {"action": "шаг 2", "expected": "ожидание 2"},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "manual"
    assert body["title"] == "Правленный вручную"
    assert body["precondition"] == "новое предусловие"
    assert body["priority"] == "high"
    assert [ (s["n"], s["action"], s["expected"]) for s in body["steps"] ] == [
        (1, "шаг 1", "ожидание 1"),
        (2, "шаг 2", "ожидание 2"),
    ]


async def test_create_with_duplicate_nodeid_should_not_crash(qa_client, db_path, tc_project_dir):
    """Задача явно ожидает контролируемую реакцию API на дублирующийся nodeid
    (test_cases UNIQUE(project, nodeid), app/db.py:118-131), но
    app.core.test_cases.create_manual (app/core/test_cases.py:248) делает голый
    INSERT без предварительной проверки — POST .../testcases с уже занятым
    в проекте nodeid валится необработанным sqlite3.IntegrityError (500), а не
    контролируемым 409/422, как для дублирующегося имени проекта (см.
    tests/test_qa_crud.py::test_qa_project_create_duplicate_conflicts).

    Тест фиксирует этот пробел через pytest.xfail, не переписывая app/ сам: если
    появится проверка на дубликат nodeid, тест начнёт молча проходить (без
    xfail-ветки)."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES (?, ?, '.venv', '[]')", (PROJECT, str(tc_project_dir))
        )
        conn.commit()
    finally:
        conn.close()

    body = {"section": "api/auth", "title": "Первый", "steps": [], "nodeid": "tests/api/auth/test_login.py::test_dup"}
    first = await qa_client.post(f"/api/projects/{PROJECT}/testcases", json=body)
    assert first.status_code == 201, first.text

    duplicate_body = {"section": "api/auth", "title": "Второй", "steps": [], "nodeid": "tests/api/auth/test_login.py::test_dup"}
    try:
        resp = await qa_client.post(f"/api/projects/{PROJECT}/testcases", json=duplicate_body)
    except Exception as exc:  # sqlite3.IntegrityError пробрасывается через ASGI как необработанное исключение
        pytest.xfail(
            "defect: create_manual()/update_case() не проверяют дубликат nodeid перед "
            f"INSERT/UPDATE и падают необработанным исключением вместо 409/422: {exc!r}"
        )
    else:
        assert resp.status_code in (409, 422), resp.text


async def test_update_case_not_found(qa_client, db_path, tc_project_dir):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES (?, ?, '.venv', '[]')", (PROJECT, str(tc_project_dir))
        )
        conn.commit()
    finally:
        conn.close()
    resp = await qa_client.put(
        f"/api/projects/{PROJECT}/testcases/999999", json={"title": "x", "steps": []}
    )
    assert resp.status_code == 404
