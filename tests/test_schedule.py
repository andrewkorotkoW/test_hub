"""Смоук-тесты ночных прогонов по расписанию (app/core/schedule.py,
app/routers/schedules.py, app/db.py::_seed_vshgu_schedules)."""
import json
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import runner, schedule
from app.db import VSHGU_PROJECT_NAME, init_db
from app.db import get_connection as db_get_connection
from app.main import app as fastapi_app

from .conftest import poll_until, register_project

PROJECT = "sched_proj"
STAND = "stage"


@pytest.fixture(autouse=True)
def _reset_schedule_module_state():
    """schedule._bot и schedule._pending_runs — модульное состояние, общее для
    всех тестов в одной pytest-сессии; изолируем его, чтобы тесты не влияли друг
    на друга (как и test_tg_bot.py делает для своих module-level структур)."""
    schedule._pending_runs.clear()
    old_bot = schedule._bot
    yield
    schedule.set_bot(old_bot)
    schedule._pending_runs.clear()


# ------------------------------------------------------------------ cron-парсер / next_run_at

def test_next_run_at_finds_next_matching_weekday_time():
    # четверг 2026-09-24, 10:00 -> ближайшие 03:00 по будням это завтра, пятница
    result = schedule.next_run_at("0 3 * * 1-5", datetime(2026, 9, 24, 10, 0))
    assert result == datetime(2026, 9, 25, 3, 0)


def test_next_run_at_skips_weekend():
    # ровно момент срабатывания (пятница 03:00) не входит сам в себя (after == candidate) ->
    # следующее срабатывание перескакивает выходные на понедельник
    result = schedule.next_run_at("0 3 * * 1-5", datetime(2026, 9, 25, 3, 0))
    assert result == datetime(2026, 9, 28, 3, 0)


def test_next_run_at_every_day_when_dow_is_star():
    result = schedule.next_run_at("30 4 * * *", datetime(2026, 9, 24, 5, 0))
    assert result == datetime(2026, 9, 25, 4, 30)


def test_parse_cron_rejects_wrong_field_count():
    with pytest.raises(ValueError):
        schedule.parse_cron("0 3 * *")


def test_parse_cron_rejects_non_star_day_of_month_or_month():
    with pytest.raises(ValueError):
        schedule.parse_cron("0 3 1 * *")
    with pytest.raises(ValueError):
        schedule.parse_cron("0 3 * 6 *")


def test_parse_cron_rejects_out_of_range_values():
    with pytest.raises(ValueError):
        schedule.parse_cron("60 3 * * *")
    with pytest.raises(ValueError):
        schedule.parse_cron("0 24 * * *")


# ------------------------------------------------------------------ сравнение прогонов (compare_runs)

def _write_allure_result(results_dir, filename, full_name, status):
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / filename).write_text(json.dumps({"fullName": full_name, "status": status}), encoding="utf-8")


def test_compare_runs_detects_new_failures_and_fixes(isolated_allure_dir):
    from app.config import settings

    prev_dir = settings.ALLURE_RESULTS_DIR / "1"
    cur_dir = settings.ALLURE_RESULTS_DIR / "2"
    _write_allure_result(prev_dir, "a-result.json", "tests.test_x#test_a", "passed")
    _write_allure_result(prev_dir, "b-result.json", "tests.test_x#test_b", "failed")
    _write_allure_result(cur_dir, "a-result.json", "tests.test_x#test_a", "failed")  # сломался
    _write_allure_result(cur_dir, "b-result.json", "tests.test_x#test_b", "passed")  # починился

    result = schedule.compare_runs(1, 2)
    assert result["newly_failed"] == ["tests.test_x#test_a"]
    assert result["newly_fixed"] == ["tests.test_x#test_b"]
    assert result["flaky"] == []


def test_compare_runs_without_previous_run_treats_all_failures_as_new(isolated_allure_dir):
    from app.config import settings

    cur_dir = settings.ALLURE_RESULTS_DIR / "5"
    _write_allure_result(cur_dir, "a-result.json", "tests.test_x#test_a", "failed")

    result = schedule.compare_runs(None, 5)
    assert result["newly_failed"] == ["tests.test_x#test_a"]
    assert result["newly_fixed"] == []


# ------------------------------------------------------------------ сидинг auto_tests_vshgu_cloude

def test_seed_creates_single_disabled_develop_schedule(db_path):
    from app.config import settings

    conn = db_get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM schedules WHERE project = ?", (VSHGU_PROJECT_NAME,)
        ).fetchall()
    finally:
        conn.close()
    # Правило владельца: stage не сидируем вообще — ровно одно расписание, develop.
    assert len(rows) == 1
    row = rows[0]
    assert row["stand"] == "develop"
    assert row["target"] == "all"
    assert row["cron"] == "0 3 * * 1-5"
    assert row["enabled"] == 0
    # Первый id из settings.TH_TG_ALLOWED_IDS (пусто в тестовом окружении -> пусто и тут;
    # реальное окружение может задавать TH_TG_ALLOWED_IDS через .env — не хардкодим).
    assert json.loads(row["notify_chat_ids"]) == sorted(settings.TH_TG_ALLOWED_IDS)[:1]


def test_seed_is_idempotent_and_does_not_duplicate(db_path):
    init_db()
    init_db()
    conn = db_get_connection()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM schedules WHERE project = ?", (VSHGU_PROJECT_NAME,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1


# ------------------------------------------------------------------ REST API CRUD

async def _setup_project_and_stand(qa_client, tmp_path):
    proj_dir = tmp_path / "sched_src_proj"
    (proj_dir / "tests").mkdir(parents=True)
    (proj_dir / "tests" / "test_sample.py").write_text("def test_ok():\n    assert True\n")
    await register_project(qa_client, PROJECT, proj_dir)
    resp = await qa_client.post(f"/api/projects/{PROJECT}/stands", json={"name": STAND, "url": "http://example.test"})
    assert resp.status_code == 201, resp.text


async def test_schedules_api_create_list_update_delete(qa_client, tmp_path):
    await _setup_project_and_stand(qa_client, tmp_path)

    create_resp = await qa_client.post(
        f"/api/projects/{PROJECT}/schedules",
        json={"stand": STAND, "target": "all", "marker": "smoke", "cron": "0 4 * * 1-5", "enabled": False, "notify_chat_ids": [111]},
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    assert created["stand"] == STAND
    assert created["marker"] == "smoke"
    assert created["enabled"] is False
    assert created["notify_chat_ids"] == [111]
    assert created["next_run_at"] is not None
    schedule_id = created["id"]

    list_resp = await qa_client.get(f"/api/projects/{PROJECT}/schedules")
    assert list_resp.status_code == 200
    assert [s["id"] for s in list_resp.json()] == [schedule_id]

    update_resp = await qa_client.put(
        f"/api/projects/{PROJECT}/schedules/{schedule_id}", json={"enabled": True, "notify_chat_ids": [222, 333]}
    )
    assert update_resp.status_code == 200, update_resp.text
    updated = update_resp.json()
    assert updated["enabled"] is True
    assert updated["notify_chat_ids"] == [222, 333]
    # marker/cron не передавались в PUT -> не изменились
    assert updated["marker"] == "smoke"
    assert updated["cron"] == "0 4 * * 1-5"

    delete_resp = await qa_client.delete(f"/api/projects/{PROJECT}/schedules/{schedule_id}")
    assert delete_resp.status_code == 204

    after_delete = await qa_client.get(f"/api/projects/{PROJECT}/schedules")
    assert after_delete.json() == []


async def _login_as(login_: str, password: str) -> AsyncClient:
    # Собственный AsyncClient, а не переиспользование фикстуры qa_client/customer_client:
    # они все делят один и тот же httpx-клиент (и его cookie), см. conftest.py и
    # тот же приём в фикстуре superadmin_client — второй login() на общем клиенте
    # затёр бы куку первого.
    transport = ASGITransport(app=fastapi_app)
    client = AsyncClient(transport=transport, base_url="http://testserver")
    resp = await client.post("/api/login", json={"login": login_, "password": password})
    assert resp.status_code == 200
    return client


async def test_schedules_api_requires_qa(qa_client, tmp_path):
    await _setup_project_and_stand(qa_client, tmp_path)
    for login_, password in (("customer", "customer"), ("manager", "manager")):
        other = await _login_as(login_, password)
        try:
            resp = await other.get(f"/api/projects/{PROJECT}/schedules")
            assert resp.status_code == 403
            resp = await other.post(f"/api/projects/{PROJECT}/schedules", json={"cron": "0 3 * * 1-5"})
            assert resp.status_code == 403
        finally:
            await other.aclose()


async def test_schedules_api_write_endpoints_require_qa_for_manager(qa_client, tmp_path):
    # Всё расписание (в отличие от флаки/xfail) закрыто ролью qa даже на чтение
    # (require_roles("qa") на всех маршрутах app/routers/schedules.py) — здесь
    # отдельно проверяем PUT/DELETE/run-now для manager, не покрытые
    # test_schedules_api_requires_qa (тот проверяет только GET/POST).
    await _setup_project_and_stand(qa_client, tmp_path)
    create_resp = await qa_client.post(
        f"/api/projects/{PROJECT}/schedules", json={"stand": STAND, "cron": "0 3 * * 1-5", "enabled": False}
    )
    schedule_id = create_resp.json()["id"]

    manager = await _login_as("manager", "manager")
    try:
        resp = await manager.put(f"/api/projects/{PROJECT}/schedules/{schedule_id}", json={"enabled": True})
        assert resp.status_code == 403
        resp = await manager.post(f"/api/projects/{PROJECT}/schedules/{schedule_id}/run-now")
        assert resp.status_code == 403
        resp = await manager.delete(f"/api/projects/{PROJECT}/schedules/{schedule_id}")
        assert resp.status_code == 403
    finally:
        await manager.aclose()


async def test_schedules_api_rejects_invalid_cron(qa_client, tmp_path):
    await _setup_project_and_stand(qa_client, tmp_path)
    resp = await qa_client.post(f"/api/projects/{PROJECT}/schedules", json={"cron": "not a cron"})
    assert resp.status_code == 422


async def test_schedules_api_rejects_unknown_stand(qa_client, tmp_path):
    await _setup_project_and_stand(qa_client, tmp_path)
    resp = await qa_client.post(
        f"/api/projects/{PROJECT}/schedules", json={"stand": "no-such-stand", "cron": "0 3 * * 1-5"}
    )
    assert resp.status_code == 404


async def test_schedules_api_run_now_unknown_id_is_404(qa_client, tmp_path):
    await _setup_project_and_stand(qa_client, tmp_path)
    resp = await qa_client.post(f"/api/projects/{PROJECT}/schedules/999/run-now")
    assert resp.status_code == 404


# ------------------------------------------------------------------ реальный прогон: run-now и last_run_id

async def test_run_now_creates_run_and_updates_last_run_id(qa_client, isolated_allure_dir, tmp_path):
    from .conftest import _with_symlinked_venv

    proj_dir = tmp_path / "sched_runnable_proj"
    (proj_dir / "tests").mkdir(parents=True)
    (proj_dir / "tests" / "test_sample.py").write_text("def test_ok():\n    assert True\n")
    _with_symlinked_venv(proj_dir)
    await register_project(qa_client, PROJECT, proj_dir)
    await qa_client.post(f"/api/projects/{PROJECT}/stands", json={"name": STAND, "url": "http://example.test"})

    create_resp = await qa_client.post(
        f"/api/projects/{PROJECT}/schedules",
        json={"stand": STAND, "target": "all", "cron": "0 3 * * 1-5", "enabled": False, "notify_chat_ids": []},
    )
    schedule_id = create_resp.json()["id"]

    run_resp = await qa_client.post(f"/api/projects/{PROJECT}/schedules/{schedule_id}/run-now")
    assert run_resp.status_code == 201, run_resp.text
    run_id = run_resp.json()["run_id"]

    async def schedule_updated():
        resp = await qa_client.get(f"/api/projects/{PROJECT}/schedules")
        row = resp.json()[0]
        return row if row["last_run_id"] == run_id else None

    updated = await poll_until(schedule_updated, timeout=10)
    assert updated is not None, "schedules.last_run_id не обновился после run-now"


# ------------------------------------------------------------------ планировщик: _tick() запускает просроченные расписания

async def test_tick_triggers_due_schedule_and_advances_next_run_at(qa_client, isolated_allure_dir, tmp_path):
    from .conftest import _with_symlinked_venv

    proj_dir = tmp_path / "sched_tick_proj"
    (proj_dir / "tests").mkdir(parents=True)
    (proj_dir / "tests" / "test_sample.py").write_text("def test_ok():\n    assert True\n")
    _with_symlinked_venv(proj_dir)
    await register_project(qa_client, PROJECT, proj_dir)
    await qa_client.post(f"/api/projects/{PROJECT}/stands", json={"name": STAND, "url": "http://example.test"})

    create_resp = await qa_client.post(
        f"/api/projects/{PROJECT}/schedules",
        json={"stand": STAND, "target": "all", "cron": "0 3 * * 1-5", "enabled": True, "notify_chat_ids": []},
    )
    schedule_id = create_resp.json()["id"]

    conn = db_get_connection()
    try:
        conn.execute("UPDATE schedules SET next_run_at = '2000-01-01T00:00:00' WHERE id = ?", (schedule_id,))
        conn.commit()
    finally:
        conn.close()

    await schedule._tick()

    conn = db_get_connection()
    try:
        row = conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
    finally:
        conn.close()
    assert row["last_run_id"] is not None
    assert row["next_run_at"] > "2000-01-01T00:00:00"

    run_id = row["last_run_id"]

    async def finished():
        resp = await qa_client.get(f"/api/projects/{PROJECT}/runs")
        r = next(x for x in resp.json() if x["id"] == run_id)
        return r if r["status"] in {"passed", "failed"} else None

    final = await poll_until(finished, timeout=20)
    assert final is not None, "прогон, запущенный планировщиком, не завершился вовремя"
    assert final["requested_by"] == "tg_bot"  # settings.TH_TG_SERVICE_LOGIN по умолчанию


# ------------------------------------------------------------------ уведомление по завершении прогона

class _FakeBot:
    def __init__(self):
        self.sent_photos: list[dict] = []
        self.sent_messages: list[dict] = []

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None):
        self.sent_photos.append({"chat_id": chat_id, "caption": caption})

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent_messages.append({"chat_id": chat_id, "text": text})


def _insert_run_row(conn, project, stand, status, counts):
    cur = conn.execute(
        "INSERT INTO runs (project, stand, target, status, started, finished, duration, requested_by, counts) "
        "VALUES (?, ?, 'all', ?, '2026-01-01T00:00:00', '2026-01-01T00:01:00', 60.0, 'tg_bot', ?)",
        (project, stand, status, json.dumps(counts)),
    )
    conn.commit()
    return cur.lastrowid


async def test_on_run_finished_sends_report_with_comparison_and_xpass(db_path, isolated_allure_dir):
    from app.config import settings

    conn = db_get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES (?, '/tmp/does-not-matter', '.venv', '[]')",
            (PROJECT,),
        )
        conn.execute("INSERT INTO stands (project, name, url, login) VALUES (?, ?, '', NULL)", (PROJECT, STAND))
        conn.commit()

        sched_row = schedule.create_schedule(conn, PROJECT, STAND, "all", None, "0 3 * * 1-5", True, [555])
        prev_run_id = _insert_run_row(conn, PROJECT, STAND, "passed", {"passed": 2, "failed": 0})
        cur_run_id = _insert_run_row(conn, PROJECT, STAND, "failed", {"passed": 1, "failed": 1})

        conn.execute(
            "INSERT INTO xfail_registry (project, stand, test, reason, first_seen, last_run_id, state) "
            "VALUES (?, ?, 'tests.test_x#test_c', NULL, '2026-01-01T00:00:00', ?, 'xpass')",
            (PROJECT, STAND, cur_run_id),
        )
        conn.commit()
    finally:
        conn.close()

    _write_allure_result(settings.ALLURE_RESULTS_DIR / str(prev_run_id), "a-result.json", "tests.test_x#test_a", "passed")
    _write_allure_result(settings.ALLURE_RESULTS_DIR / str(cur_run_id), "a-result.json", "tests.test_x#test_a", "failed")

    fake_bot = _FakeBot()
    schedule.set_bot(fake_bot)
    schedule._pending_runs[cur_run_id] = (sched_row["id"], prev_run_id)

    await schedule.on_run_finished(cur_run_id)

    assert cur_run_id not in schedule._pending_runs
    assert len(fake_bot.sent_photos) == 1
    sent = fake_bot.sent_photos[0]
    assert sent["chat_id"] == 555
    assert "test_a" in sent["caption"]
    assert "Новые падения" in sent["caption"]
    assert "xpass" in sent["caption"]


async def test_on_run_finished_is_noop_for_unknown_run_id(db_path):
    fake_bot = _FakeBot()
    schedule.set_bot(fake_bot)
    await schedule.on_run_finished(999999)
    assert fake_bot.sent_photos == []
    assert fake_bot.sent_messages == []


async def test_on_run_finished_skips_notification_without_chat_ids(db_path, isolated_allure_dir):
    conn = db_get_connection()
    try:
        conn.execute(
            "INSERT INTO projects (name, path, venv, stands) VALUES (?, '/tmp/does-not-matter', '.venv', '[]')",
            (PROJECT,),
        )
        conn.execute("INSERT INTO stands (project, name, url, login) VALUES (?, ?, '', NULL)", (PROJECT, STAND))
        conn.commit()
        sched_row = schedule.create_schedule(conn, PROJECT, STAND, "all", None, "0 3 * * 1-5", True, [])
        run_id = _insert_run_row(conn, PROJECT, STAND, "passed", {"passed": 1, "failed": 0})
    finally:
        conn.close()

    fake_bot = _FakeBot()
    schedule.set_bot(fake_bot)
    schedule._pending_runs[run_id] = (sched_row["id"], None)

    await schedule.on_run_finished(run_id)
    assert fake_bot.sent_photos == []
    assert fake_bot.sent_messages == []


# ------------------------------------------------------------------ интеграция с runner._finalize (register_finalize_hook)

async def test_runner_finalize_hook_triggers_schedule_notification(qa_client, isolated_allure_dir, tmp_path):
    from .conftest import _with_symlinked_venv

    proj_dir = tmp_path / "sched_hook_proj"
    (proj_dir / "tests").mkdir(parents=True)
    (proj_dir / "tests" / "test_sample.py").write_text("def test_ok():\n    assert True\n")
    _with_symlinked_venv(proj_dir)
    await register_project(qa_client, PROJECT, proj_dir)
    await qa_client.post(f"/api/projects/{PROJECT}/stands", json={"name": STAND, "url": "http://example.test"})

    create_resp = await qa_client.post(
        f"/api/projects/{PROJECT}/schedules",
        json={"stand": STAND, "target": "all", "cron": "0 3 * * 1-5", "enabled": False, "notify_chat_ids": [777]},
    )
    schedule_id = create_resp.json()["id"]

    fake_bot = _FakeBot()
    schedule.set_bot(fake_bot)
    runner.register_finalize_hook(schedule.on_run_finished)
    try:
        run_resp = await qa_client.post(f"/api/projects/{PROJECT}/schedules/{schedule_id}/run-now")
        run_id = run_resp.json()["run_id"]

        async def notified():
            return (fake_bot.sent_photos or fake_bot.sent_messages) or None

        result = await poll_until(notified, timeout=20)
        assert result is not None, "хук app.core.runner._finalize не отправил уведомление о прогоне по расписанию"
        chat_ids = {p["chat_id"] for p in fake_bot.sent_photos} | {m["chat_id"] for m in fake_bot.sent_messages}
        assert chat_ids == {777}
    finally:
        runner.unregister_finalize_hook(schedule.on_run_finished)
