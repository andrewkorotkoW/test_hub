"""REST API «Новых дефектов» (app/routers/new_defects.py) через app/main.py —
по образцу tests/test_xfail.py/test_sentry_api.py: db_path + qa_client/
manager_client фикстуры из tests/conftest.py."""
import httpx
import pytest

from app.config import settings
from app.core import youtrack
from app.db import get_connection

PROJECT = "nd_api_proj"
STAND = "stand"


@pytest.fixture(autouse=True)
def _youtrack_unconfigured_by_default(monkeypatch):
    """Тесты не должны зависеть от реального workspace/.env (владелец настроил
    там боевой TH_YOUTRACK_* для продакшен-инстанса, см. app/core/youtrack.py) —
    по умолчанию YouTrack тут всегда "не настроен"; youtrack_configured ниже
    явно переопределяет на тестовые значения там, где это нужно сценарию."""
    monkeypatch.setattr(settings, "TH_YOUTRACK_URL", "")
    monkeypatch.setattr(settings, "TH_YOUTRACK_TOKEN", "")
    monkeypatch.setattr(settings, "TH_YOUTRACK_ISSUE", "")


@pytest.fixture()
def project_and_stand(db_path):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES (?, '/tmp/nd_api_proj', '.venv', '[]')",
            (PROJECT,),
        )
        conn.execute("INSERT INTO stands (project, name, url, login) VALUES (?, ?, '', NULL)", (PROJECT, STAND))
        cur = conn.execute(
            "INSERT INTO runs (project, stand, target, status, started, requested_by, counts) "
            "VALUES (?, ?, 'all', 'failed', '2026-01-01T00:00:00', 'qa', '{}')",
            (PROJECT, STAND),
        )
        run_id = cur.lastrowid
        conn.execute(
            "INSERT INTO run_test_results (run_id, nodeid, full_name, status, duration, cause, finished_ts) "
            "VALUES (?, 'tests/api/test_a.py::test_a', 'pkg.test_a#test_a', 'failed', 1.0, 'code', "
            "'2026-01-01T00:01:00')",
            (run_id,),
        )
        conn.commit()
    finally:
        conn.close()
    return run_id


@pytest.fixture()
def youtrack_configured(monkeypatch):
    monkeypatch.setattr(settings, "TH_YOUTRACK_URL", "https://tracker.example.ru")
    monkeypatch.setattr(settings, "TH_YOUTRACK_TOKEN", "secret-token")
    monkeypatch.setattr(settings, "TH_YOUTRACK_ISSUE", "PROJ-1")


async def test_list_returns_candidate_connected_false_without_youtrack(qa_client, project_and_stand):
    run_id = project_and_stand
    resp = await qa_client.get(
        f"/api/projects/{PROJECT}/new-defects", params={"stand": STAND, "run_id": run_id}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is False
    assert len(data["items"]) == 1
    assert data["items"][0]["full_name"] == "pkg.test_a#test_a"


async def test_list_connected_true_when_youtrack_configured(qa_client, project_and_stand, youtrack_configured):
    run_id = project_and_stand
    resp = await qa_client.get(
        f"/api/projects/{PROJECT}/new-defects", params={"stand": STAND, "run_id": run_id}
    )
    assert resp.json()["connected"] is True


async def test_decide_dismissed_works_without_youtrack(qa_client, project_and_stand):
    run_id = project_and_stand
    resp = await qa_client.post(
        f"/api/projects/{PROJECT}/new-defects/decide",
        params={"stand": STAND},
        json={"full_name": "pkg.test_a#test_a", "run_id": run_id, "status": "dismissed"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "dismissed"
    assert body["issue_url"] is None

    # повторный GET списка кандидатов больше не содержит этот тест
    listed = await qa_client.get(
        f"/api/projects/{PROJECT}/new-defects", params={"stand": STAND, "run_id": run_id}
    )
    assert listed.json()["items"] == []


async def test_decide_confirmed_without_youtrack_returns_503(qa_client, project_and_stand):
    run_id = project_and_stand
    resp = await qa_client.post(
        f"/api/projects/{PROJECT}/new-defects/decide",
        params={"stand": STAND},
        json={"full_name": "pkg.test_a#test_a", "run_id": run_id, "status": "confirmed"},
    )
    assert resp.status_code == 503


def _install_youtrack_mock(monkeypatch):
    """Возвращает список захваченных httpx.Request — проверяем не только факт
    отправки, но и реальный текст комментария (регрессия 17.10.2026: комментарий
    уходил без ФР/трейса/шагов/серьёзности — тело запроса собиралось только из
    того, что инженер вписал руками, без обогащения из allure)."""
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"id": "4-999"})

    def fake_post(url, *, headers=None, params=None, json=None, timeout=None):
        with httpx.Client(transport=httpx.MockTransport(handler)) as c:
            return c.post(url, headers=headers, params=params, json=json, timeout=timeout)

    monkeypatch.setattr(youtrack.httpx, "post", fake_post)
    return calls


async def test_decide_confirmed_comment_includes_auto_fields_from_allure(
    qa_client, project_and_stand, youtrack_configured, monkeypatch
):
    """full_name в project_and_stand — tests/api/test_a.py::test_a, без сырого
    allure-результата на диске (только строка run_test_results), поэтому severity/
    steps/message у кандидата пустые — здесь нужен сам факт, что в комментарий
    попадают nodeid/приоритет/пред_условие/ОР (то, что реально есть), а полный
    набор с message/severity/steps/trace отдельно проверен ниже, с allure-файлом."""
    run_id = project_and_stand
    calls = _install_youtrack_mock(monkeypatch)

    resp = await qa_client.post(
        f"/api/projects/{PROJECT}/new-defects/decide",
        params={"stand": STAND},
        json={
            "full_name": "pkg.test_a#test_a", "run_id": run_id, "status": "confirmed",
            "priority": "Высокий", "expected_result": "тест ОР", "precondition": "тест ПУ",
        },
    )
    assert resp.status_code == 201
    assert len(calls) == 1
    import json as json_mod
    sent_text = json_mod.loads(calls[0].content)["text"]
    assert "pkg.test_a#test_a" in sent_text
    assert "Приоритет: Высокий" in sent_text
    assert "тест ПУ" in sent_text
    assert "тест ОР" in sent_text
    assert "tests/api/test_a.py::test_a" in sent_text  # Тест: <nodeid> в хвосте


def test_step_line_does_not_double_number_already_numbered_allure_steps():
    """@allure.step в auto_tests_vshgu уже пишут «1. Создать курс…» — в комментарии
    выходило «1 - 1. Создать курс…» (замечание владельца 20.10.2026)."""
    from app.routers.new_defects import _step_line

    assert _step_line(0, "шаг раз") == "1 - шаг раз"
    assert _step_line(3, "4. Дождаться обработки контекста") == "4. Дождаться обработки контекста"
    assert _step_line(0, " 1) Открыть карточку ") == "1) Открыть карточку"
    assert _step_line(1, "2 - Включить переключатель") == "2 - Включить переключатель"
    assert _step_line(0, "10 минут ждать") == "1 - 10 минут ждать", "число без разделителя — не нумерация"


async def test_decide_confirmed_comment_includes_message_severity_steps_trace(
    db_path, isolated_allure_dir, qa_client, youtrack_configured, monkeypatch
):
    import json as json_mod

    from app.db import get_connection

    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES (?, '/tmp/nd_rich', '.venv', '[]')",
            ("nd_rich_proj",),
        )
        conn.execute(
            "INSERT INTO stands (project, name, url, login) VALUES ('nd_rich_proj', 'stand', '', NULL)"
        )
        cur = conn.execute(
            "INSERT INTO runs (project, stand, target, status, started, requested_by, counts) "
            "VALUES ('nd_rich_proj', 'stand', 'all', 'failed', '2026-01-01T00:00:00', 'qa', '{}')"
        )
        run_id = cur.lastrowid
        conn.execute(
            "INSERT INTO run_test_results (run_id, nodeid, full_name, status, duration, cause, finished_ts) "
            "VALUES (?, 'tests/ui/test_b.py::test_b', 'pkg.test_b#test_b', 'broken', 1.0, 'code', "
            "'2026-01-01T00:01:00')",
            (run_id,),
        )
        conn.commit()
    finally:
        conn.close()

    from app.config import settings
    results_dir = settings.ALLURE_RESULTS_DIR / str(run_id)
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "00-result.json").write_text(json_mod.dumps({
        "fullName": "pkg.test_b#test_b",
        "status": "broken",
        "labels": [{"name": "severity", "value": "critical"}],
        "steps": [{"name": "шаг раз", "status": "passed"}, {"name": "шаг два упал", "status": "failed"}],
        "statusDetails": {"message": "KeyError: 'data'", "trace": "где-то в UserCrudController.php"},
    }), encoding="utf-8")

    calls = _install_youtrack_mock(monkeypatch)
    resp = await qa_client.post(
        "/api/projects/nd_rich_proj/new-defects/decide",
        params={"stand": "stand"},
        json={"full_name": "pkg.test_b#test_b", "run_id": run_id, "status": "confirmed"},
    )
    assert resp.status_code == 201
    sent_text = json_mod.loads(calls[0].content)["text"]
    assert "Front" in sent_text  # tests/ui/... -> Front
    assert "Серьёзность: Critical" in sent_text
    assert "1 - шаг раз" in sent_text and "2 - шаг два упал" in sent_text
    assert "ФР: KeyError: 'data'" in sent_text
    assert "где-то в UserCrudController.php" in sent_text


async def test_decide_confirmed_posts_to_youtrack_and_stores_issue_url(
    qa_client, project_and_stand, youtrack_configured, monkeypatch
):
    run_id = project_and_stand
    _install_youtrack_mock(monkeypatch)

    resp = await qa_client.post(
        f"/api/projects/{PROJECT}/new-defects/decide",
        params={"stand": STAND},
        json={
            "full_name": "pkg.test_a#test_a", "run_id": run_id, "status": "confirmed",
            "priority": "Высокий", "expected_result": "ОР", "precondition": "ПУ",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "confirmed"
    assert body["issue_url"] == "https://tracker.example.ru/issue/PROJ-1"
    assert body["priority"] == "Высокий"


async def test_customer_cannot_decide(customer_client, project_and_stand, youtrack_configured):
    run_id = project_and_stand
    resp = await customer_client.post(
        f"/api/projects/{PROJECT}/new-defects/decide",
        params={"stand": STAND},
        json={"full_name": "pkg.test_a#test_a", "run_id": run_id, "status": "dismissed"},
    )
    assert resp.status_code == 403


async def test_manager_can_decide(manager_client, project_and_stand):
    run_id = project_and_stand
    resp = await manager_client.post(
        f"/api/projects/{PROJECT}/new-defects/decide",
        params={"stand": STAND},
        json={"full_name": "pkg.test_a#test_a", "run_id": run_id, "status": "dismissed"},
    )
    assert resp.status_code == 201
