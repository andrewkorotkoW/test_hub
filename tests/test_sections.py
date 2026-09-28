"""Юнит-тесты app/core/sections.py — дерево разделов проекта (сканирование
tests/ без запуска pytest, кэш по mtime), см. миссию, часть 3."""
import os
import time

from app.core import sections


def test_count_test_functions_counts_top_level_and_class_methods(tmp_path):
    path = tmp_path / "test_x.py"
    path.write_text(
        "import pytest\n\n"
        "def test_one():\n    assert True\n\n"
        "async def test_two():\n    assert True\n\n"
        "def helper():\n    pass\n\n"
        "class TestGroup:\n"
        "    def test_three(self):\n        assert True\n"
        "    def not_a_test(self):\n        pass\n"
    )
    assert sections._count_test_functions(path) == 3


def test_count_test_functions_syntax_error_returns_zero(tmp_path):
    path = tmp_path / "test_broken.py"
    path.write_text("def test_x(:\n    pass\n")
    assert sections._count_test_functions(path) == 0


def test_count_test_functions_missing_file_returns_zero(tmp_path):
    assert sections._count_test_functions(tmp_path / "does_not_exist.py") == 0


def _write_test(path, tests_count=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"def test_{i}():\n    assert True\n" for i in range(tests_count))
    path.write_text(body)


def test_discover_builds_kinds_areas_files_tree(tmp_path):
    root = tmp_path / "proj"
    _write_test(root / "tests" / "api" / "notifications" / "test_list.py", tests_count=2)
    _write_test(root / "tests" / "api" / "notifications" / "test_get.py", tests_count=1)
    _write_test(root / "tests" / "ui" / "buk" / "test_form.py", tests_count=3)
    _write_test(root / "tests" / "e2e" / "test_checkout.py", tests_count=1)

    tree = sections.discover(str(root))

    kinds = {k["kind"]: k for k in tree["kinds"]}
    assert set(kinds) == {"api", "ui", "e2e"}
    assert kinds["api"]["target"] == "tests/api"

    api_areas = {a["section"]: a for a in kinds["api"]["areas"]}
    assert set(api_areas) == {"api/notifications"}
    notif = api_areas["api/notifications"]
    assert notif["area"] == "notifications"
    assert notif["target"] == "tests/api/notifications"
    assert notif["tests_count"] == 3
    assert {f["name"] for f in notif["files"]} == {"test_list.py", "test_get.py"}
    file_get = next(f for f in notif["files"] if f["name"] == "test_get.py")
    assert file_get["target"] == "tests/api/notifications/test_get.py"
    assert file_get["tests_count"] == 1

    ui_areas = {a["section"]: a for a in kinds["ui"]["areas"]}
    assert ui_areas["ui/buk"]["tests_count"] == 3

    e2e_areas = kinds["e2e"]["areas"]
    assert len(e2e_areas) == 1
    assert e2e_areas[0]["area"] is None
    assert e2e_areas[0]["section"] == "e2e"
    assert e2e_areas[0]["target"] == "tests/e2e"
    assert e2e_areas[0]["tests_count"] == 1


def test_discover_files_in_nested_subfolders_are_included(tmp_path):
    root = tmp_path / "proj"
    _write_test(root / "tests" / "ui" / "notifications" / "admin" / "test_a.py", tests_count=1)
    _write_test(root / "tests" / "ui" / "notifications" / "user" / "test_b.py", tests_count=1)

    tree = sections.discover(str(root))
    kinds = {k["kind"]: k for k in tree["kinds"]}
    area = kinds["ui"]["areas"][0]
    assert area["tests_count"] == 2
    names = {f["name"] for f in area["files"]}
    assert names == {"admin/test_a.py", "user/test_b.py"}


def test_discover_skips_areas_without_any_test_files(tmp_path):
    root = tmp_path / "proj"
    (root / "tests" / "api" / "empty_area").mkdir(parents=True)
    (root / "tests" / "api" / "empty_area" / "helper.py").write_text("x = 1\n")
    _write_test(root / "tests" / "api" / "notifications" / "test_a.py")

    tree = sections.discover(str(root))
    kinds = {k["kind"]: k for k in tree["kinds"]}
    areas = {a["area"] for a in kinds["api"]["areas"]}
    assert areas == {"notifications"}


def test_discover_skips_dunder_and_hidden_dirs(tmp_path):
    root = tmp_path / "proj"
    _write_test(root / "tests" / "api" / "notifications" / "test_a.py")
    (root / "tests" / "api" / "__pycache__").mkdir(parents=True)
    (root / "tests" / "api" / "__pycache__" / "test_ghost.py").write_text("def test_x():\n    pass\n")
    (root / "tests" / "api" / ".hidden").mkdir(parents=True)
    (root / "tests" / "api" / ".hidden" / "test_ghost2.py").write_text("def test_x():\n    pass\n")

    tree = sections.discover(str(root))
    kinds = {k["kind"]: k for k in tree["kinds"]}
    areas = {a["area"] for a in kinds["api"]["areas"]}
    assert areas == {"notifications"}


def test_discover_no_tests_dir_returns_empty_kinds(tmp_path):
    tree = sections.discover(str(tmp_path / "no_such_project"))
    assert tree == {"kinds": []}


def test_discover_files_directly_under_kind_dir_are_not_scanned(tmp_path):
    """Файлы прямо в tests/api (не в подпапке-области) не попадают в дерево —
    та же граница, что и у app.core.stats.discover_section_dirs."""
    root = tmp_path / "proj"
    (root / "tests" / "api").mkdir(parents=True)
    (root / "tests" / "api" / "test_root.py").write_text("def test_x():\n    pass\n")

    tree = sections.discover(str(root))
    assert tree == {"kinds": []}


# ------------------------------------------------------------------ mtime_signature

def test_mtime_signature_changes_when_file_added(tmp_path):
    root = tmp_path / "proj"
    _write_test(root / "tests" / "api" / "notifications" / "test_a.py")
    sig_before = sections.mtime_signature(str(root))

    _write_test(root / "tests" / "api" / "notifications" / "test_b.py")
    sig_after = sections.mtime_signature(str(root))

    assert sig_before[0] == 1
    assert sig_after[0] == 2
    assert sig_after != sig_before


def test_mtime_signature_changes_when_file_modified(tmp_path):
    root = tmp_path / "proj"
    path = root / "tests" / "api" / "notifications" / "test_a.py"
    _write_test(path)
    sig_before = sections.mtime_signature(str(root))

    future = time.time() + 5
    os.utime(path, (future, future))
    sig_after = sections.mtime_signature(str(root))

    assert sig_after[0] == sig_before[0]
    assert sig_after[1] != sig_before[1]


def test_mtime_signature_stable_without_changes(tmp_path):
    root = tmp_path / "proj"
    _write_test(root / "tests" / "api" / "notifications" / "test_a.py")
    assert sections.mtime_signature(str(root)) == sections.mtime_signature(str(root))


def test_mtime_signature_missing_tests_dir(tmp_path):
    assert sections.mtime_signature(str(tmp_path / "no_such_project")) == [0, 0.0]


# ------------------------------------------------------------------ recalc()/load_cached()

def test_recalc_writes_cache_and_load_cached_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(sections, "SECTIONS_DIR", tmp_path / "sections_cache")
    root = tmp_path / "proj"
    _write_test(root / "tests" / "api" / "notifications" / "test_a.py")

    result = sections.recalc("proj_x", str(root))
    assert result["project"] == "proj_x"
    assert result["mtime_signature"] == sections.mtime_signature(str(root))
    assert sections.cache_path("proj_x").is_file()

    cached = sections.load_cached("proj_x")
    assert cached == result


def test_load_cached_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(sections, "SECTIONS_DIR", tmp_path / "sections_cache")
    assert sections.load_cached("no_such_project") is None


def test_load_cached_corrupt_json_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(sections, "SECTIONS_DIR", tmp_path / "sections_cache")
    path = sections.cache_path("proj_x")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json", encoding="utf-8")
    assert sections.load_cached("proj_x") is None
