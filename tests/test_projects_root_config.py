"""TH_PROJECTS_ROOT/TH_VSHGU_PATH (см. app/config.py) — корень соседних с test_hub
проектов (bike_fit, Velo_bot, auto_tests_vshgu) и явный путь к VSHGU, задача t1 из
docs/missions/2026-09-30_server_readiness.md. До задачи путь был хардкожен по логину
владельца; теперь читается из окружения, а дефолт ищет ближайшего предка с именем
"PycharmProjects" (не просто BASE_DIR.parent — во вложенном git worktree BASE_DIR.parent
это не PycharmProjects, см. testhub-projects-root-config-worktree-pitfall в памяти)."""
import importlib.util
import sqlite3
from pathlib import Path

from app.config import settings

CONFIG_PATH = Path(__file__).resolve().parent.parent / "app" / "config.py"


def _load_isolated_config(monkeypatch):
    """Как в tests/test_allure_bin.py::_load_isolated_config - грузит app/config.py в
    отдельный, незакэшированный модуль, глуша dotenv.load_dotenv, чтобы monkeypatch.setenv/
    delenv управляли значением, а не .env владельца репозитория."""
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)
    spec = importlib.util.spec_from_file_location("_test_isolated_projects_root_config", CONFIG_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_th_projects_root_reads_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TH_PROJECTS_ROOT", str(tmp_path))
    monkeypatch.delenv("TH_VSHGU_PATH", raising=False)
    isolated = _load_isolated_config(monkeypatch)

    assert isolated.settings.TH_PROJECTS_ROOT == tmp_path


def test_th_vshgu_path_reads_from_env_independently_of_projects_root(tmp_path, monkeypatch):
    custom_vshgu = tmp_path / "custom_vshgu_checkout"
    monkeypatch.setenv("TH_PROJECTS_ROOT", str(tmp_path / "unused_root"))
    monkeypatch.setenv("TH_VSHGU_PATH", str(custom_vshgu))
    isolated = _load_isolated_config(monkeypatch)

    assert isolated.settings.TH_VSHGU_PATH == custom_vshgu


def test_th_vshgu_path_defaults_to_projects_root_subdir(tmp_path, monkeypatch):
    monkeypatch.setenv("TH_PROJECTS_ROOT", str(tmp_path))
    monkeypatch.delenv("TH_VSHGU_PATH", raising=False)
    isolated = _load_isolated_config(monkeypatch)

    assert isolated.settings.TH_VSHGU_PATH == tmp_path / "auto_tests_vshgu"


def test_default_projects_root_finds_pycharmprojects_ancestor(monkeypatch):
    # Ничего не переопределяем - в этом воркетри BASE_DIR реально лежит под
    # .../PycharmProjects/cyber_office/workspace/worktrees/<id>, так что дефолт должен
    # найти этого предка, а не голый BASE_DIR.parent (который был бы .../worktrees/<id>
    # или, при обычном клонировании без worktree, вообще PycharmProjects - тест ниже
    # проверяет именно нетривиальный вложенный случай напрямую).
    monkeypatch.delenv("TH_PROJECTS_ROOT", raising=False)
    isolated = _load_isolated_config(monkeypatch)

    assert isolated.settings.TH_PROJECTS_ROOT.name == "PycharmProjects"
    assert isolated.BASE_DIR != isolated.settings.TH_PROJECTS_ROOT
    assert isolated.settings.TH_PROJECTS_ROOT in isolated.BASE_DIR.parents


def test_default_projects_root_walks_up_multiple_levels_for_nested_worktree(monkeypatch, tmp_path):
    monkeypatch.delenv("TH_PROJECTS_ROOT", raising=False)
    isolated = _load_isolated_config(monkeypatch)

    nested = tmp_path / "PycharmProjects" / "test_hub" / "workspace" / "worktrees" / "deadbeef"
    nested.mkdir(parents=True)
    monkeypatch.setattr(isolated, "BASE_DIR", nested)

    assert isolated._default_projects_root() == tmp_path / "PycharmProjects"


def test_default_projects_root_falls_back_to_parent_when_no_pycharmprojects_ancestor(monkeypatch, tmp_path):
    monkeypatch.delenv("TH_PROJECTS_ROOT", raising=False)
    isolated = _load_isolated_config(monkeypatch)

    no_match = tmp_path / "opt" / "test_hub"
    no_match.mkdir(parents=True)
    monkeypatch.setattr(isolated, "BASE_DIR", no_match)

    assert isolated._default_projects_root() == tmp_path / "opt"


def test_th_projects_root_default_is_not_hardcoded_owner_login(monkeypatch):
    # Регрессия на исходный баг задачи: дефолт не должен содержать буквальный путь
    # владельца, зашитый строкой (например "/Users/andreykorotkow/...") - только
    # вычисленный от расположения репозитория.
    monkeypatch.delenv("TH_PROJECTS_ROOT", raising=False)
    isolated = _load_isolated_config(monkeypatch)

    assert isolated.settings.TH_PROJECTS_ROOT.is_absolute()
    assert isolated.settings.TH_PROJECTS_ROOT in (isolated.BASE_DIR, *isolated.BASE_DIR.parents)


def test_seed_projects_skipped_when_configured_path_does_not_exist(tmp_path, monkeypatch):
    """Регресс на существующую логику (app/db.py::_seed_if_empty/_seed_vshgu_project):
    несуществующий путь означает "нечего сидировать", а не ошибку - раннер всё равно не
    найдёт venv/bin/python по такому пути. Подменяем сами константы SEED_PROJECTS/
    VSHGU_PROJECT_PATH заведомо несуществующими путями внутри tmp_path, а не полагаемся
    на то, что реальных соседних проектов на машине нет (в этом воркетри они как раз
    есть, см. test_vshgu_seed.py)."""
    from app import db

    ghost_bike_path = tmp_path / "does_not_exist" / "bike_fit"
    ghost_vshgu_path = tmp_path / "does_not_exist" / "auto_tests_vshgu"
    monkeypatch.setattr(db, "SEED_PROJECTS", [("ghost_bike", str(ghost_bike_path), ".venv")])
    monkeypatch.setattr(db, "VSHGU_PROJECT_PATH", str(ghost_vshgu_path))

    db_path = tmp_path / "test_hub.db"
    monkeypatch.setattr(settings, "DB_PATH", db_path)
    db.init_db()

    conn = sqlite3.connect(db_path)
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM projects").fetchall()}
    finally:
        conn.close()

    assert "ghost_bike" not in names
    assert db.VSHGU_PROJECT_NAME not in names
