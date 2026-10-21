"""Вкладка «Данные» проекта — генерация тестовых данных на стенде через CLI проекта
тестов (app/core/datagen.py, app/routers/datagen.py).

Вместо настоящего test_data_generation/generate.py (auto_tests_vshgu: сеть, .env, стенд)
в tmp-проект кладётся его заглушка с тем же контрактом: --list --json печатает JSON-список
сценариев, --scenario ... --json --manifest-out PATH пишет манифест и печатает строку
«__TH_DATAGEN_RESULT__ {json}», --cleanup PATH --json печатает итог удаления. Заглушка
записывает свои argv и переменные окружения в файл — так проверяется, что test_hub передаёт
стенд (STAND_URL/STAND_LOGIN, --env), количество и префикс так же, как раннер pytest."""
import json
import sys
from pathlib import Path

import pytest

from app.core import datagen

from .conftest import poll_until, register_project

PROJECT = "datagen_proj"
STAND = "develop"

_FAKE_GENERATOR = r'''
import json, os, sys, time
from pathlib import Path

MARKER = "__TH_DATAGEN_RESULT__"
HERE = Path(__file__).resolve().parent
(HERE / "calls.jsonl").open("a", encoding="utf-8").write(json.dumps({
    "argv": sys.argv[1:],
    "cwd": os.getcwd(),
    "STAND_URL": os.environ.get("STAND_URL"),
    "STAND_LOGIN": os.environ.get("STAND_LOGIN"),
}, ensure_ascii=False) + "\n")

args = sys.argv[1:]
def opt(name, default=None):
    return args[args.index(name) + 1] if name in args else default

if "--list" in args:
    print(json.dumps([
        {"name": "users", "title": "Пользователи по ролям", "category": "Пользователи", "description": "N пользователей", "count_help": "пользователей"},
        {"name": "boom", "description": "падает после первой сущности", "count_help": "—"},
        {"name": "slow", "description": "спит", "count_help": "—"},
    ], ensure_ascii=False))
    sys.exit(0)

if "--cleanup" in args:
    manifest = json.loads(Path(opt("--cleanup")).read_text(encoding="utf-8"))
    results, failed = [], 0
    for entry in reversed(manifest["created"]):
        status = "failed" if entry["entity"] == "stubborn" else "deleted"
        failed += status == "failed"
        print(f"{entry['entity']} {entry['id']} {status}")
        results.append({"entity": entry["entity"], "id": entry["id"], "status": status, "note": None})
    print(MARKER + " " + json.dumps({"ok": failed == 0, "dry_run": False, "deleted": len(results) - failed,
                                     "failed": failed, "skipped": 0, "results": results}, ensure_ascii=False))
    sys.exit(0 if failed == 0 else 1)

scenario = opt("--scenario")
count = int(opt("--count", "1"))
out = Path(opt("--manifest-out"))
env_name = opt("--env", "develop")
print(f"Сценарий: {scenario}, окружение: {env_name}, count={count}")
print("Authorization: Bearer super-secret-token")
if scenario == "slow":
    time.sleep(1.5)
created = [{"entity": "user", "id": 100 + i, "how_to_delete": "users.delete(user_id)"} for i in range(count)]
created.append({"entity": "program", "id": 555, "how_to_delete": "programs.mass_delete([id])"})
if scenario == "boom":
    created = created[:1]
    manifest = {"env": env_name, "scenario": scenario, "created": created, "skipped": []}
    out.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    print(MARKER + " " + json.dumps({"ok": False, "partial": True, "error": "RuntimeError: 500 на втором шаге",
                                     "manifest_path": str(out), "manifest": manifest}, ensure_ascii=False))
    sys.exit(1)
if scenario == "stubborn":
    created.append({"entity": "stubborn", "id": 1, "how_to_delete": "—"})
manifest = {"env": env_name, "scenario": scenario, "created": created,
            "skipped": [{"entity": "lpd", "reason": "только stage"}]}
out.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
print("Готово.")
print(MARKER + " " + json.dumps({"ok": True, "dry_run": False, "manifest_path": str(out), "manifest": manifest},
                                ensure_ascii=False))
'''


def _make_project(tmp_path, with_generator=True):
    proj = tmp_path / "datagen_src"
    (proj / "tests").mkdir(parents=True)
    (proj / "tests" / "test_sample.py").write_text("def test_ok():\n    assert True\n")
    bin_dir = proj / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").symlink_to(sys.executable)
    if with_generator:
        gen_dir = proj / "test_data_generation"
        gen_dir.mkdir()
        (gen_dir / "generate.py").write_text(_FAKE_GENERATOR, encoding="utf-8")
    return proj


def _calls(proj):
    path = proj / "test_data_generation" / "calls.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture()
def isolated_workspace(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "WORKSPACE_DIR", tmp_path / "workspace")
    return tmp_path / "workspace"


async def _setup(qa_client, tmp_path, with_generator=True, use_env_flag=True):
    proj = _make_project(tmp_path, with_generator=with_generator)
    await register_project(qa_client, PROJECT, proj)
    if use_env_flag:
        resp = await qa_client.put(f"/api/projects/{PROJECT}", json={"use_env_flag": True})
        assert resp.status_code == 200, resp.text
    resp = await qa_client.post(
        f"/api/projects/{PROJECT}/stands", json={"name": STAND, "url": "https://portal-dev.example", "login": "admin@example"}
    )
    assert resp.status_code == 201, resp.text
    return proj


async def _wait_status(client, batch_id, statuses, timeout=10.0):
    async def check():
        resp = await client.get(f"/api/projects/{PROJECT}/data/{batch_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        return body if body["status"] in statuses else None

    result = await poll_until(check, timeout=timeout)
    assert result is not None, f"партия {batch_id} не дошла до {statuses}"
    return result


# ------------------------------------------------------------------ сценарии

async def test_scenarios_come_from_project_cli(qa_client, tmp_path, isolated_workspace):
    proj = await _setup(qa_client, tmp_path)
    resp = await qa_client.get(f"/api/projects/{PROJECT}/data/scenarios")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["supported"] is True
    assert [s["name"] for s in body["scenarios"]] == ["users", "boom", "slow"]
    assert body["scenarios"][0] == {"name": "users", "title": "Пользователи по ролям", "category": "Пользователи",
                                    "description": "N пользователей", "count_help": "пользователей"}
    # без title/category в выводе CLI — title = name, category пустая (старые версии generate.py)
    assert body["scenarios"][1] == {"name": "boom", "title": "boom", "category": "",
                                    "description": "падает после первой сущности", "count_help": "—"}
    assert _calls(proj)[-1]["argv"] == ["--list", "--json"]

    # второй запрос — из кэша (generate.py и scenarios/ не менялись), CLI не зовётся повторно
    before = len(_calls(proj))
    resp = await qa_client.get(f"/api/projects/{PROJECT}/data/scenarios")
    assert resp.status_code == 200
    assert len(_calls(proj)) == before


async def test_project_without_generator_is_unsupported(qa_client, tmp_path, isolated_workspace):
    await _setup(qa_client, tmp_path, with_generator=False)
    resp = await qa_client.get(f"/api/projects/{PROJECT}/data/scenarios")
    assert resp.status_code == 200
    assert resp.json() == {"supported": False, "scenarios": []}
    resp = await qa_client.post(f"/api/projects/{PROJECT}/data", json={"scenario": "users"})
    assert resp.status_code == 422
    assert "generate.py" in resp.json()["detail"]


# ------------------------------------------------------------------ создание партии

async def test_create_batch_runs_cli_with_stand_and_stores_manifest(qa_client, tmp_path, isolated_workspace):
    proj = await _setup(qa_client, tmp_path)
    resp = await qa_client.post(
        f"/api/projects/{PROJECT}/data",
        json={"scenario": "users", "stand": STAND, "count": 3, "prefix": "VSHGU2-2412"},
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["status"] == "queued"
    assert created["created_by"] == "qa"
    assert created["stand"] == STAND and created["count"] == 3 and created["prefix"] == "VSHGU2-2412"
    batch_id = created["id"]

    done = await _wait_status(qa_client, batch_id, ("done", "failed"))
    assert done["status"] == "done", done
    assert done["error"] is None
    assert done["created_total"] == 4 and done["skipped_total"] == 1
    assert done["entities"] == [{"entity": "user", "count": 3}, {"entity": "program", "count": 1}]
    assert done["manifest"]["scenario"] == "users"
    assert done["manifest"]["created"][3] == {"entity": "program", "id": 555, "how_to_delete": "programs.mass_delete([id])"}
    assert "Готово." in done["log"]
    assert "Сценарий: users, окружение: develop, count=3" in done["log"]
    assert "__TH_DATAGEN_RESULT__" not in done["log"], "строка-маркер не должна попадать в лог"
    assert "super-secret-token" not in done["log"], "секреты в логе маскируются как у раннера"
    assert done["finished_at"]

    call = _calls(proj)[-1]
    argv = call["argv"]
    # как у раннера: сначала стенд (--env), затем параметры самой команды
    assert argv[:2] == ["--env", STAND]
    assert argv[argv.index("--scenario") + 1] == "users"
    assert "--count" in argv and argv[argv.index("--count") + 1] == "3"
    assert "--prefix" in argv and argv[argv.index("--prefix") + 1] == "VSHGU2-2412"
    assert "--json" in argv
    assert "--env" in argv and argv[argv.index("--env") + 1] == STAND
    assert argv[argv.index("--manifest-out") + 1] == str(datagen.manifest_path(batch_id))
    assert call["STAND_URL"] == "https://portal-dev.example" and call["STAND_LOGIN"] == "admin@example"
    assert call["cwd"] == str(proj)
    assert datagen.manifest_path(batch_id).exists()

    listed = await qa_client.get(f"/api/projects/{PROJECT}/data")
    assert listed.status_code == 200
    assert [b["id"] for b in listed.json()] == [batch_id]
    assert "manifest" not in listed.json()[0] and "log" not in listed.json()[0]


async def test_create_without_env_flag_and_stand_passes_no_env(qa_client, tmp_path, isolated_workspace):
    proj = await _setup(qa_client, tmp_path, use_env_flag=False)
    resp = await qa_client.post(f"/api/projects/{PROJECT}/data", json={"scenario": "users"})
    assert resp.status_code == 201, resp.text
    await _wait_status(qa_client, resp.json()["id"], ("done", "failed"))
    call = _calls(proj)[-1]
    assert "--env" not in call["argv"]
    assert call["STAND_URL"] is None


async def test_failed_scenario_keeps_partial_manifest(qa_client, tmp_path, isolated_workspace):
    await _setup(qa_client, tmp_path)
    resp = await qa_client.post(f"/api/projects/{PROJECT}/data", json={"scenario": "boom", "stand": STAND})
    assert resp.status_code == 201, resp.text
    failed = await _wait_status(qa_client, resp.json()["id"], ("done", "failed"))
    assert failed["status"] == "failed"
    assert failed["error"] == "RuntimeError: 500 на втором шаге"
    assert failed["created_total"] == 1
    assert failed["entities"] == [{"entity": "user", "count": 1}]


async def test_create_validation(qa_client, tmp_path, isolated_workspace):
    await _setup(qa_client, tmp_path)
    base = f"/api/projects/{PROJECT}/data"
    resp = await qa_client.post(base, json={"scenario": "nope"})
    assert resp.status_code == 422 and "nope" in resp.json()["detail"]
    resp = await qa_client.post(base, json={"scenario": "users", "count": 0})
    assert resp.status_code == 422
    resp = await qa_client.post(base, json={"scenario": "users", "count": 51})
    assert resp.status_code == 422
    resp = await qa_client.post(base, json={"scenario": "users", "prefix": "с пробелом"})
    assert resp.status_code == 422
    resp = await qa_client.post(base, json={"scenario": "users", "stand": "ghost"})
    assert resp.status_code == 404
    resp = await qa_client.get("/api/projects/ghost/data/scenarios")
    assert resp.status_code == 404


async def test_second_batch_while_first_is_running_is_409(qa_client, tmp_path, isolated_workspace):
    await _setup(qa_client, tmp_path)
    resp = await qa_client.post(f"/api/projects/{PROJECT}/data", json={"scenario": "slow", "stand": STAND})
    assert resp.status_code == 201, resp.text
    first = resp.json()["id"]
    resp = await qa_client.post(f"/api/projects/{PROJECT}/data", json={"scenario": "users", "stand": STAND})
    assert resp.status_code == 409
    assert f"#{first}" in resp.json()["detail"]
    await _wait_status(qa_client, first, ("done", "failed"))
    resp = await qa_client.post(f"/api/projects/{PROJECT}/data", json={"scenario": "users", "stand": STAND})
    assert resp.status_code == 201


# ------------------------------------------------------------------ удаление данных

async def test_delete_runs_cleanup_and_marks_batch_deleted(qa_client, tmp_path, isolated_workspace):
    proj = await _setup(qa_client, tmp_path)
    resp = await qa_client.post(f"/api/projects/{PROJECT}/data", json={"scenario": "users", "stand": STAND, "count": 2})
    batch_id = resp.json()["id"]
    await _wait_status(qa_client, batch_id, ("done",))

    # файл манифеста могли почистить — перед --cleanup он переписывается из БД
    datagen.manifest_path(batch_id).unlink()

    resp = await qa_client.delete(f"/api/projects/{PROJECT}/data/{batch_id}")
    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "deleting"
    deleted = await _wait_status(qa_client, batch_id, ("deleted", "delete_failed"))
    assert deleted["status"] == "deleted", deleted
    assert deleted["deleted_at"]
    assert deleted["cleanup_summary"] == {"deleted": 3, "failed": 0, "skipped": 0}
    assert [r["entity"] for r in deleted["cleanup"]["results"]] == ["program", "user", "user"], "в обратном порядке"
    assert "program 555 deleted" in deleted["delete_log"]
    assert deleted["log"], "лог создания сохраняется"

    call = _calls(proj)[-1]
    assert call["argv"] == ["--env", STAND, "--cleanup", str(datagen.manifest_path(batch_id)), "--json"]
    assert call["STAND_URL"] == "https://portal-dev.example"

    # повторно удалить уже удалённую партию нельзя
    resp = await qa_client.delete(f"/api/projects/{PROJECT}/data/{batch_id}")
    assert resp.status_code == 409


async def test_delete_with_failed_entities_is_delete_failed_and_retryable(qa_client, tmp_path, isolated_workspace):
    await _setup(qa_client, tmp_path)
    resp = await qa_client.post(f"/api/projects/{PROJECT}/data", json={"scenario": "stubborn", "stand": STAND})
    # 'stubborn' нет в --list -> 422; создаём обычную партию и подменяем манифест в БД
    assert resp.status_code == 422
    resp = await qa_client.post(f"/api/projects/{PROJECT}/data", json={"scenario": "users", "stand": STAND})
    batch_id = resp.json()["id"]
    done = await _wait_status(qa_client, batch_id, ("done",))
    manifest = done["manifest"]
    manifest["created"].append({"entity": "stubborn", "id": 1, "how_to_delete": "—"})
    from app.db import get_connection

    conn = get_connection()
    try:
        conn.execute("UPDATE data_batches SET manifest = ? WHERE id = ?", (json.dumps(manifest), batch_id))
        conn.commit()
    finally:
        conn.close()

    resp = await qa_client.delete(f"/api/projects/{PROJECT}/data/{batch_id}")
    assert resp.status_code == 202, resp.text
    result = await _wait_status(qa_client, batch_id, ("deleted", "delete_failed"))
    assert result["status"] == "delete_failed"
    assert result["cleanup_summary"] == {"deleted": 2, "failed": 1, "skipped": 0}
    assert "не удалено сущностей: 1" in result["error"]
    # delete_failed — можно попробовать ещё раз
    resp = await qa_client.delete(f"/api/projects/{PROJECT}/data/{batch_id}")
    assert resp.status_code == 202


async def test_delete_of_failed_batch_without_manifest_is_409(qa_client, tmp_path, isolated_workspace):
    await _setup(qa_client, tmp_path)
    resp = await qa_client.post(f"/api/projects/{PROJECT}/data", json={"scenario": "users", "stand": STAND})
    batch_id = resp.json()["id"]
    await _wait_status(qa_client, batch_id, ("done",))
    from app.db import get_connection

    conn = get_connection()
    try:
        conn.execute("UPDATE data_batches SET manifest = NULL, status = 'failed' WHERE id = ?", (batch_id,))
        conn.commit()
    finally:
        conn.close()
    resp = await qa_client.delete(f"/api/projects/{PROJECT}/data/{batch_id}")
    assert resp.status_code == 409
    resp = await qa_client.delete(f"/api/projects/{PROJECT}/data/999")
    assert resp.status_code == 404


# ------------------------------------------------------------------ роли и восстановление

async def test_data_endpoints_require_qa(qa_client, manager_client_factory, tmp_path, isolated_workspace):
    await _setup(qa_client, tmp_path)
    for login_, password in (("manager", "manager"), ("customer", "customer")):
        other = await manager_client_factory(login_, password)
        try:
            assert (await other.get(f"/api/projects/{PROJECT}/data/scenarios")).status_code == 403
            assert (await other.get(f"/api/projects/{PROJECT}/data")).status_code == 403
            assert (await other.post(f"/api/projects/{PROJECT}/data", json={"scenario": "users"})).status_code == 403
            assert (await other.delete(f"/api/projects/{PROJECT}/data/1")).status_code == 403
        finally:
            await other.aclose()


@pytest.fixture()
def manager_client_factory():
    from httpx import ASGITransport, AsyncClient

    from app.main import app as fastapi_app

    async def _make(login_, password):
        transport = ASGITransport(app=fastapi_app)
        client = AsyncClient(transport=transport, base_url="http://testserver")
        resp = await client.post("/api/login", json={"login": login_, "password": password})
        assert resp.status_code == 200
        return client

    return _make


def test_recover_stale_marks_unfinished_batches_failed(db_path, isolated_workspace):
    from app.db import get_connection

    conn = get_connection()
    try:
        conn.execute("INSERT INTO projects (name, path, venv, stands, use_env_flag) VALUES (?, ?, ?, '[]', 0)",
                     (PROJECT, "/nonexistent", ".venv"))
        for status in ("queued", "running", "deleting", "done"):
            conn.execute(
                "INSERT INTO data_batches (project, stand, scenario, count, status, created_at) VALUES (?, NULL, 'users', 1, ?, ?)",
                (PROJECT, status, "2026-10-21T10:00:00"),
            )
        conn.commit()
        running_id = conn.execute("SELECT id FROM data_batches WHERE status = 'running'").fetchone()["id"]
    finally:
        conn.close()
    # манифест, который CLI успела записать в файл до рестарта, подхватывается в БД
    path = datagen.manifest_path(running_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"env": "develop", "scenario": "users", "created": [{"entity": "user", "id": 1, "how_to_delete": "x"}], "skipped": []}))

    assert datagen.recover_stale() == 3

    conn = get_connection()
    try:
        rows = conn.execute("SELECT status, error, manifest FROM data_batches ORDER BY id").fetchall()
    finally:
        conn.close()
    assert [r["status"] for r in rows] == ["failed", "failed", "delete_failed", "done"]
    assert rows[0]["error"] == "test_hub был перезапущен до завершения"
    assert rows[3]["error"] is None
    assert json.loads(rows[1]["manifest"])["created"][0]["id"] == 1


def test_main_uses_core_datagen_not_router_in_lifespan():
    """В app/main.py модуль-роутер datagen импортируется из .routers под своим именем —
    ядро должно жить под псевдонимом datagen_core, иначе lifespan звал бы
    recover_stale у роутера (так и упал первый запуск под launchd 21.10.2026)."""
    from app import main as main_module

    assert main_module.datagen_core is datagen
    assert callable(main_module.datagen_core.recover_stale)
    assert main_module.datagen is not datagen, "имя datagen в main.py — роутер, не ядро"


def test_entity_counts_and_row_to_dict_tolerate_broken_json():
    assert datagen.entity_counts(None) == []
    assert datagen.entity_counts({"created": [{"entity": "user"}, {"entity": "user"}, {"entity": "program"}]}) == [
        {"entity": "user", "count": 2}, {"entity": "program", "count": 1},
    ]
    assert datagen._parse_json("{not json") is None
    assert datagen._parse_scenarios('noise\n[{"name": "a", "description": "d"}]\n') == [
        {"name": "a", "title": "a", "category": "", "description": "d", "count_help": ""}
    ]
    with pytest.raises(datagen.DatagenError):
        datagen._parse_scenarios("no json here")
