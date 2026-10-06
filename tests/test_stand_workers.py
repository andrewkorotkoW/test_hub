"""stands.workers — поле «Потоки (pytest -n)» для параллельного прогона по стенду
(docs/missions/2026-10-06_stand_workers.md): миграция колонки app/db.py, поле
StandCreate/StandUpdate.workers (валидация 0..16), API create/update/list стендов
отдают и принимают workers, `-n <workers>` в args раннера (app/core/runner.py::
_execute) только когда workers > 0 и прогон не live и repeat <= 1 (эфир и
флаки-детектор не совместимы с параллельными воркерами).

Написано по образцу tests/test_run_live_flag.py / tests/test_runs_mobile_flag.py:
миграция и API — обычные unit/integration-тесты; факт передачи `-n` в pytest
проверяется реальным прогоном на фикстурном проекте через probe.json, который
дампит из pytest_configure() значение `config.option.numprocesses` — это именно
то, что устанавливает CLI-опция `-n` плагина pytest-xdist (requirements.txt не
упоминает pytest-xdist явно, но пакет установлен в окружении — иначе сам флаг
был бы бессмысленным; см. app/core/runner.py::_execute).
"""
import json
import sqlite3
import sys

from app.config import settings
from app.db import init_db

from .conftest import poll_until, register_project


# ------------------------------------------------------------------ миграция колонки

def test_migration_adds_workers_column_to_old_stands_table_without_it(tmp_path, monkeypatch):
    old_db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(old_db_path)
    conn.execute(
        "CREATE TABLE stands ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "project TEXT NOT NULL,"
        "name TEXT NOT NULL,"
        "url TEXT NOT NULL,"
        "login TEXT,"
        "manual_only INTEGER NOT NULL DEFAULT 0,"
        "sentry_project TEXT,"
        "sentry_environment TEXT,"
        "UNIQUE (project, name)"
        ")"
    )
    conn.execute(
        "INSERT INTO stands (id, project, name, url) VALUES (1, 'legacy_proj', 'develop', 'http://x')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(settings, "DB_PATH", old_db_path)
    init_db()  # не должно падать на старой БД без stands.workers

    conn = sqlite3.connect(old_db_path)
    conn.row_factory = sqlite3.Row
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(stands)").fetchall()}
        assert "workers" in cols

        old_row = conn.execute("SELECT * FROM stands WHERE id = 1").fetchone()
        assert old_row["workers"] == 0  # ALTER TABLE ... DEFAULT 0 -> существующая строка получает 0, не NULL

        conn.execute(
            "INSERT INTO stands (project, name, url, workers) VALUES ('legacy_proj', 'stage', 'http://y', 4)"
        )
        conn.commit()
        new_row = conn.execute("SELECT * FROM stands WHERE workers = 4").fetchone()
        assert new_row is not None
    finally:
        conn.close()

    init_db()  # повторный запуск (рестарт сервиса) на уже мигрированной БД идемпотентен


def test_fresh_db_stands_table_already_has_workers_column(db_path):
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(stands)").fetchall()}
        assert "workers" in cols
    finally:
        conn.close()


# ------------------------------------------------------------------ API: create/update/list

async def test_create_stand_with_workers_saves_and_returns_it(qa_client, tmp_path):
    await register_project(qa_client, "workers_api_proj", tmp_path)
    resp = await qa_client.post(
        "/api/projects/workers_api_proj/stands",
        json={"name": "k8s", "url": "http://k8s.example", "workers": 4},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["workers"] == 4
    stand_id = body["id"]

    list_resp = await qa_client.get("/api/projects/workers_api_proj/stands")
    row = next(s for s in list_resp.json() if s["id"] == stand_id)
    assert row["workers"] == 4


async def test_create_stand_without_workers_defaults_to_zero(qa_client, tmp_path):
    await register_project(qa_client, "workers_default_proj", tmp_path)
    resp = await qa_client.post(
        "/api/projects/workers_default_proj/stands",
        json={"name": "develop", "url": "http://develop.example"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["workers"] == 0


async def test_update_stand_workers_changes_it_and_other_fields_unchanged(qa_client, tmp_path):
    await register_project(qa_client, "workers_update_proj", tmp_path)
    create_resp = await qa_client.post(
        "/api/projects/workers_update_proj/stands",
        json={"name": "develop", "url": "http://develop.example", "login": "op"},
    )
    stand_id = create_resp.json()["id"]
    assert create_resp.json()["workers"] == 0

    update_resp = await qa_client.put(
        f"/api/projects/workers_update_proj/stands/{stand_id}", json={"workers": 8}
    )
    assert update_resp.status_code == 200
    body = update_resp.json()
    assert body["workers"] == 8
    assert body["login"] == "op"  # не переданное в update поле сохранилось

    # повторный update без workers -> значение сохраняется прежним, не сбрасывается в 0
    update_resp2 = await qa_client.put(
        f"/api/projects/workers_update_proj/stands/{stand_id}", json={"login": "op2"}
    )
    assert update_resp2.status_code == 200
    assert update_resp2.json()["workers"] == 8
    assert update_resp2.json()["login"] == "op2"


async def test_create_stand_workers_boundary_zero_and_sixteen_are_valid(qa_client, tmp_path):
    await register_project(qa_client, "workers_boundary_proj", tmp_path)
    resp_zero = await qa_client.post(
        "/api/projects/workers_boundary_proj/stands",
        json={"name": "zero", "url": "http://x", "workers": 0},
    )
    assert resp_zero.status_code == 201, resp_zero.text
    assert resp_zero.json()["workers"] == 0

    resp_sixteen = await qa_client.post(
        "/api/projects/workers_boundary_proj/stands",
        json={"name": "sixteen", "url": "http://x", "workers": 16},
    )
    assert resp_sixteen.status_code == 201, resp_sixteen.text
    assert resp_sixteen.json()["workers"] == 16


async def test_create_stand_workers_out_of_range_is_422(qa_client, tmp_path):
    await register_project(qa_client, "workers_out_of_range_proj", tmp_path)

    resp_negative = await qa_client.post(
        "/api/projects/workers_out_of_range_proj/stands",
        json={"name": "negative", "url": "http://x", "workers": -1},
    )
    assert resp_negative.status_code == 422, resp_negative.text

    resp_too_many = await qa_client.post(
        "/api/projects/workers_out_of_range_proj/stands",
        json={"name": "too-many", "url": "http://x", "workers": 17},
    )
    assert resp_too_many.status_code == 422, resp_too_many.text


async def test_update_stand_workers_out_of_range_is_422(qa_client, tmp_path):
    await register_project(qa_client, "workers_update_range_proj", tmp_path)
    create_resp = await qa_client.post(
        "/api/projects/workers_update_range_proj/stands",
        json={"name": "develop", "url": "http://develop.example"},
    )
    stand_id = create_resp.json()["id"]

    resp = await qa_client.put(
        f"/api/projects/workers_update_range_proj/stands/{stand_id}", json={"workers": 17}
    )
    assert resp.status_code == 422, resp.text


# ------------------------------------------------------------------ раннер: -n <workers> в args

_PROBE_CONFTEST = '''\
import json
import os
from pathlib import Path


def pytest_configure(config):
    # Воркеры pytest-xdist сами перезапускают сбор conftest.py (PYTEST_XDIST_WORKER
    # в их окружении) -- пишем только из главного процесса, иначе запись
    # перезатиралась бы одновременно несколькими воркерами.
    if os.environ.get("PYTEST_XDIST_WORKER"):
        return
    entry = {"numprocesses": config.option.numprocesses}
    log_path = Path(__file__).parent / "probe.log"
    with log_path.open("a") as f:
        f.write(json.dumps(entry) + "\\n")
'''

_TWO_TESTS = '''\
def test_one():
    assert True


def test_two():
    assert True
'''


def _probe_project_dir(tmp_path, name="workers_probe_proj"):
    proj = tmp_path / name
    (proj / "tests").mkdir(parents=True)
    (proj / "tests" / "test_probe.py").write_text(_TWO_TESTS)
    (proj / "conftest.py").write_text(_PROBE_CONFTEST)
    bin_dir = proj / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").symlink_to(sys.executable)
    return proj


def _read_probe_log(project_dir):
    log_path = project_dir / "probe.log"
    return [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]


async def _create_stand(client, project_name, stand_name, workers):
    resp = await client.post(
        f"/api/projects/{project_name}/stands",
        json={"name": stand_name, "url": "http://stand.example", "workers": workers},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _run_and_wait(client, project_name, body, timeout=30):
    resp = await client.post(f"/api/projects/{project_name}/runs", json=body)
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["id"]

    async def finished():
        rows = (await client.get(f"/api/projects/{project_name}/runs")).json()
        row = next(r for r in rows if r["id"] == run_id)
        return row if row["status"] in {"passed", "failed"} else None

    final = await poll_until(finished, timeout=timeout)
    assert final is not None, "прогон не завершился вовремя"
    return run_id, final


async def test_stand_workers_four_adds_dash_n_four_to_runner_args(qa_client, isolated_allure_dir, tmp_path):
    proj_dir = _probe_project_dir(tmp_path)
    await register_project(qa_client, "workers_n4_proj", proj_dir)
    await _create_stand(qa_client, "workers_n4_proj", "k8s", 4)

    run_id, final = await _run_and_wait(
        qa_client, "workers_n4_proj", {"stand": "k8s", "target": "tests/test_probe.py"}
    )
    assert final["status"] == "passed", final

    entries = _read_probe_log(proj_dir)
    assert entries, "pytest_configure должен был отработать хотя бы раз"
    assert any(e["numprocesses"] == 4 for e in entries), entries


async def test_stand_workers_zero_does_not_add_dash_n(qa_client, isolated_allure_dir, tmp_path):
    proj_dir = _probe_project_dir(tmp_path, "workers_n0_proj")
    await register_project(qa_client, "workers_n0_proj", proj_dir)
    await _create_stand(qa_client, "workers_n0_proj", "develop", 0)

    run_id, final = await _run_and_wait(
        qa_client, "workers_n0_proj", {"stand": "develop", "target": "tests/test_probe.py"}
    )
    assert final["status"] == "passed", final

    entries = _read_probe_log(proj_dir)
    assert entries
    assert all(e["numprocesses"] is None for e in entries), entries


async def test_run_without_stand_does_not_add_dash_n(qa_client, isolated_allure_dir, tmp_path):
    """Прогон без выбранного стенда (stand=None) -- нет stand["workers"] вовсе,
    args собираются как раньше, без -n."""
    proj_dir = _probe_project_dir(tmp_path, "workers_no_stand_proj")
    await register_project(qa_client, "workers_no_stand_proj", proj_dir)

    run_id, final = await _run_and_wait(
        qa_client, "workers_no_stand_proj", {"target": "tests/test_probe.py"}
    )
    assert final["status"] == "passed", final

    entries = _read_probe_log(proj_dir)
    assert entries
    assert all(e["numprocesses"] is None for e in entries), entries


async def test_live_true_with_workers_four_does_not_add_dash_n(qa_client, isolated_allure_dir, tmp_path):
    """live=true -> эфир транслирует кадры одного процесса, несколько воркеров
    их перемешали бы -- -n не добавляется даже при workers=4 у стенда."""
    proj_dir = _probe_project_dir(tmp_path, "workers_live_proj")
    await register_project(qa_client, "workers_live_proj", proj_dir)
    await _create_stand(qa_client, "workers_live_proj", "k8s", 4)

    run_id, final = await _run_and_wait(
        qa_client,
        "workers_live_proj",
        {"stand": "k8s", "target": "tests/test_probe.py::test_one", "live": True},
    )
    assert final["status"] == "passed", final
    assert final["live"] is True

    entries = _read_probe_log(proj_dir)
    assert entries
    assert all(e["numprocesses"] is None for e in entries), entries


async def test_repeat_with_workers_four_does_not_add_dash_n_on_any_attempt(
    qa_client, isolated_allure_dir, tmp_path
):
    """repeat>1 (флаки-детектор) гоняет одну цель последовательно -- -n не
    добавляется ни на одном из повторов, даже если у стенда workers=4."""
    proj_dir = _probe_project_dir(tmp_path, "workers_repeat_proj")
    await register_project(qa_client, "workers_repeat_proj", proj_dir)
    await _create_stand(qa_client, "workers_repeat_proj", "k8s", 4)

    run_id, final = await _run_and_wait(
        qa_client,
        "workers_repeat_proj",
        {"stand": "k8s", "target": "tests/test_probe.py::test_one", "repeat": 3},
        timeout=45,
    )
    assert final["status"] == "passed", final

    entries = _read_probe_log(proj_dir)
    assert len(entries) == 3, entries  # по одной записи от главного процесса на каждый из 3 повторов
    assert all(e["numprocesses"] is None for e in entries), entries


# ------------------------------------------------------------------ UI smoke: форма стенда

import pathlib  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ADMIN_HTML = (REPO_ROOT / "ui" / "admin.html").read_text()
ADMIN_JS = (REPO_ROOT / "ui" / "admin.js").read_text()


async def test_admin_html_has_workers_field_served_over_http(client):
    resp = await client.get("/admin.html")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="stand-workers"' in html
    assert 'type="number"' in html


def test_admin_html_stand_form_has_workers_input_with_valid_range():
    assert 'id="stand-workers" type="number" min="0" max="16"' in ADMIN_HTML


def test_admin_js_badge_marks_name_with_multiplier_when_workers_positive():
    assert 's.workers > 0 ? ` <span class="muted">×${s.workers}</span>` : ""' in ADMIN_JS


def test_admin_js_edit_button_carries_workers_dataset():
    assert 'data-workers="${s.workers || 0}"' in ADMIN_JS
    assert 'standWorkers.value = editBtn.dataset.workers || "0";' in ADMIN_JS


def test_admin_js_submit_payload_includes_workers_as_int():
    assert 'workers: standWorkers.value === "" ? 0 : parseInt(standWorkers.value, 10),' in ADMIN_JS
