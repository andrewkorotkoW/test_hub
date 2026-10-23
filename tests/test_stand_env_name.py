"""stands.env_name — значение для --env раннера (app/core/runner.py), когда оно
должно отличаться от имени стенда: кастомные/ревью-стенды с use_env_flag=true,
где имя стенда в test_hub — просто ярлык (например "2066" для ревью-ветки), а
проект тестов понимает только свои литералы --env (develop/stage/stand и т.п.,
см. ENVIRONMENTS в auto_tests_vshgu/config/environments.py). NULL (по умолчанию,
все существующие стенды) -> раннер использует имя стенда буквально, как раньше.

Найдено 23.10.2026 владельцем на реальном стенде VSHGU "2066": раннер слал
`--env 2066`, а допустимые значения проекта — только develop/stage/prod/k8s/stand,
прогон падал мгновенно с argparse-ошибкой ("ERROR: ... invalid choice: '2066'").

Пароль для такого стенда test_hub в БД не хранит (решение владельца 23.10.2026,
см. тот же разговор): TH_STAND_PASSWORD_<PROJECT> — один общий пароль на проект
в .env самого test_hub, не новое поле в stands/API.

Написано по образцу tests/test_stand_workers.py: миграция и API — обычные
unit/integration-тесты; то, что раннер реально передаёт нужный --env/STAND_PASSWORD,
проверяется реальным прогоном на фикстурном проекте через probe.json, который
дампит из pytest_configure() значение опции --env и переменной STAND_PASSWORD —
так же, как test_stand_workers.py дампит config.option.numprocesses.
"""
import json
import sqlite3
import sys

from app.config import settings
from app.db import init_db

from .conftest import poll_until, register_project


# ------------------------------------------------------------------ миграция колонки

def test_migration_adds_env_name_column_to_old_stands_table_without_it(tmp_path, monkeypatch):
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
        "workers INTEGER NOT NULL DEFAULT 0,"
        "UNIQUE (project, name)"
        ")"
    )
    conn.execute(
        "INSERT INTO stands (id, project, name, url) VALUES (1, 'legacy_proj', '2066', 'http://x')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(settings, "DB_PATH", old_db_path)
    init_db()  # не должно падать на старой БД без stands.env_name

    conn = sqlite3.connect(old_db_path)
    conn.row_factory = sqlite3.Row
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(stands)").fetchall()}
        assert "env_name" in cols

        old_row = conn.execute("SELECT * FROM stands WHERE id = 1").fetchone()
        assert old_row["env_name"] is None  # ALTER TABLE без DEFAULT -> NULL у существующей строки

        conn.execute(
            "INSERT INTO stands (project, name, url, env_name) VALUES ('legacy_proj', 'review', 'http://y', 'stand')"
        )
        conn.commit()
        new_row = conn.execute("SELECT * FROM stands WHERE env_name = 'stand'").fetchone()
        assert new_row is not None
    finally:
        conn.close()

    init_db()  # повторный запуск (рестарт сервиса) на уже мигрированной БД идемпотентен


def test_fresh_db_stands_table_already_has_env_name_column(db_path):
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(stands)").fetchall()}
        assert "env_name" in cols
    finally:
        conn.close()


# ------------------------------------------------------------------ API: create/update/list

async def test_create_stand_with_env_name_saves_and_returns_it(qa_client, tmp_path):
    await register_project(qa_client, "env_name_api_proj", tmp_path)
    resp = await qa_client.post(
        "/api/projects/env_name_api_proj/stands",
        json={"name": "2066", "url": "http://review.example", "env_name": "stand"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["env_name"] == "stand"
    stand_id = body["id"]

    list_resp = await qa_client.get("/api/projects/env_name_api_proj/stands")
    row = next(s for s in list_resp.json() if s["id"] == stand_id)
    assert row["env_name"] == "stand"


async def test_create_stand_without_env_name_defaults_to_null(qa_client, tmp_path):
    await register_project(qa_client, "env_name_default_proj", tmp_path)
    resp = await qa_client.post(
        "/api/projects/env_name_default_proj/stands",
        json={"name": "develop", "url": "http://develop.example"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["env_name"] is None


async def test_update_stand_env_name_changes_it_and_other_fields_unchanged(qa_client, tmp_path):
    await register_project(qa_client, "env_name_update_proj", tmp_path)
    create_resp = await qa_client.post(
        "/api/projects/env_name_update_proj/stands",
        json={"name": "2412", "url": "http://review.example", "login": "op"},
    )
    stand_id = create_resp.json()["id"]
    assert create_resp.json()["env_name"] is None

    update_resp = await qa_client.put(
        f"/api/projects/env_name_update_proj/stands/{stand_id}", json={"env_name": "stand"}
    )
    assert update_resp.status_code == 200
    body = update_resp.json()
    assert body["env_name"] == "stand"
    assert body["login"] == "op"  # не переданное в update поле сохранилось

    # повторный update без env_name -> значение сохраняется прежним, не сбрасывается в null
    update_resp2 = await qa_client.put(
        f"/api/projects/env_name_update_proj/stands/{stand_id}", json={"login": "op2"}
    )
    assert update_resp2.status_code == 200
    assert update_resp2.json()["env_name"] == "stand"
    assert update_resp2.json()["login"] == "op2"


# ------------------------------------------------------------------ раннер: --env и STAND_PASSWORD

_PROBE_CONFTEST = '''\
import json
import os
from pathlib import Path


def pytest_addoption(parser):
    parser.addoption("--env", action="store", default="develop")


def pytest_configure(config):
    entry = {
        "env": config.getoption("--env"),
        "stand_password": os.environ.get("STAND_PASSWORD"),
        "stand_url": os.environ.get("STAND_URL"),
    }
    log_path = Path(__file__).parent / "probe.log"
    with log_path.open("a") as f:
        f.write(json.dumps(entry) + "\\n")
'''

_ONE_TEST = '''\
def test_one():
    assert True
'''


def _probe_project_dir(tmp_path, name="env_name_probe_proj"):
    proj = tmp_path / name
    (proj / "tests").mkdir(parents=True)
    (proj / "tests" / "test_probe.py").write_text(_ONE_TEST)
    (proj / "conftest.py").write_text(_PROBE_CONFTEST)
    bin_dir = proj / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").symlink_to(sys.executable)
    return proj


def _read_probe_log(project_dir):
    log_path = project_dir / "probe.log"
    return [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]


async def _create_stand(client, project_name, stand_name, url, env_name=None):
    resp = await client.post(
        f"/api/projects/{project_name}/stands",
        json={"name": stand_name, "url": url, "env_name": env_name},
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


async def test_stand_without_env_name_passes_stand_name_as_env_literally(
    qa_client, isolated_allure_dir, tmp_path
):
    """Без env_name поведение не меняется -- раннер шлёт --env <имя стенда>, как
    и до этой миссии (develop/stage/k8s так и работают)."""
    proj_dir = _probe_project_dir(tmp_path, "env_name_literal_proj")
    await register_project(qa_client, "env_name_literal_proj", proj_dir)
    await qa_client.put("/api/projects/env_name_literal_proj", json={"use_env_flag": True})
    await _create_stand(qa_client, "env_name_literal_proj", "develop", "http://develop.example")

    run_id, final = await _run_and_wait(
        qa_client, "env_name_literal_proj", {"stand": "develop", "target": "tests/test_probe.py"}
    )
    assert final["status"] == "passed", final

    entries = _read_probe_log(proj_dir)
    assert entries
    assert all(e["env"] == "develop" for e in entries), entries


async def test_stand_with_env_name_overrides_the_literal_passed_to_env_flag(
    qa_client, isolated_allure_dir, tmp_path
):
    """С env_name="stand" раннер шлёт --env stand, а не имя стенда ("2066") —
    воспроизведение и фикс реальной находки владельца 23.10.2026."""
    proj_dir = _probe_project_dir(tmp_path, "env_name_override_proj")
    await register_project(qa_client, "env_name_override_proj", proj_dir)
    await qa_client.put("/api/projects/env_name_override_proj", json={"use_env_flag": True})
    await _create_stand(
        qa_client, "env_name_override_proj", "2066", "http://review-2066.example", env_name="stand"
    )

    run_id, final = await _run_and_wait(
        qa_client, "env_name_override_proj", {"stand": "2066", "target": "tests/test_probe.py"}
    )
    assert final["status"] == "passed", final

    entries = _read_probe_log(proj_dir)
    assert entries
    assert all(e["env"] == "stand" for e in entries), entries
    assert all(e["stand_url"] == "http://review-2066.example" for e in entries), entries


async def test_stand_password_env_var_set_from_project_scoped_th_setting(
    qa_client, isolated_allure_dir, tmp_path, monkeypatch
):
    """TH_STAND_PASSWORD_<PROJECT> (переменная окружения самого test_hub, не поле
    в БД) попадает в STAND_PASSWORD дочернего pytest-процесса."""
    proj_dir = _probe_project_dir(tmp_path, "env_name_password_proj")
    await register_project(qa_client, "env_name_password_proj", proj_dir)
    await qa_client.put("/api/projects/env_name_password_proj", json={"use_env_flag": True})
    await _create_stand(
        qa_client, "env_name_password_proj", "2066", "http://review.example", env_name="stand"
    )

    monkeypatch.setenv("TH_STAND_PASSWORD_ENV_NAME_PASSWORD_PROJ", "super-secret-test-password")

    run_id, final = await _run_and_wait(
        qa_client, "env_name_password_proj", {"stand": "2066", "target": "tests/test_probe.py"}
    )
    assert final["status"] == "passed", final

    entries = _read_probe_log(proj_dir)
    assert entries
    assert all(e["stand_password"] == "super-secret-test-password" for e in entries), entries


async def test_stand_password_env_var_absent_when_not_configured(
    qa_client, isolated_allure_dir, tmp_path, monkeypatch
):
    """Без TH_STAND_PASSWORD_<PROJECT> в окружении test_hub -- STAND_PASSWORD дочернему
    процессу просто не передаётся (None), ничего не падает на этом шаге."""
    proj_dir = _probe_project_dir(tmp_path, "env_name_no_password_proj")
    await register_project(qa_client, "env_name_no_password_proj", proj_dir)
    await qa_client.put("/api/projects/env_name_no_password_proj", json={"use_env_flag": True})
    await _create_stand(
        qa_client, "env_name_no_password_proj", "2066", "http://review.example", env_name="stand"
    )

    monkeypatch.delenv("TH_STAND_PASSWORD_ENV_NAME_NO_PASSWORD_PROJ", raising=False)

    run_id, final = await _run_and_wait(
        qa_client, "env_name_no_password_proj", {"stand": "2066", "target": "tests/test_probe.py"}
    )
    assert final["status"] == "passed", final

    entries = _read_probe_log(proj_dir)
    assert entries
    assert all(e["stand_password"] is None for e in entries), entries


# ------------------------------------------------------------------ UI smoke: форма стенда

import pathlib  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
STANDS_HTML = (REPO_ROOT / "ui" / "stands.html").read_text()
STANDS_JS = (REPO_ROOT / "ui" / "stands.js").read_text()


async def test_stands_html_has_env_name_field_served_over_http(client):
    resp = await client.get("/stands.html")
    assert resp.status_code == 200
    assert 'id="stand-env-name"' in resp.text


def test_stands_js_submit_payload_includes_env_name():
    assert 'env_name: standEnvName.value.trim() || null,' in STANDS_JS


def test_stands_js_edit_button_carries_env_name_dataset():
    assert 'data-env-name="${escapeHtml(s.env_name || "")}"' in STANDS_JS
    assert 'standEnvName.value = editBtn.dataset.envName || "";' in STANDS_JS
