"""Дерево разделов проекта (api/ui/e2e -> области -> файлы) без запуска pytest —
для формы запуска и формы расписаний (см. миссию, часть 3).

Раздел (область) здесь — то же самое понятие, что и в app.core.stats
(_section_of_full_name/discover_section_dirs): подпапка tests/api/<area> или
tests/ui/<area>, либо весь tests/e2e целиком одним разделом. В отличие от
stats.py, который узнаёт про раздел только из allure-results прошедшего
прогона, это чисто файловый скан — тест ни разу не запускавшийся всё равно
попадёт в дерево (иначе форму запуска нечем было бы наполнить до первого
прогона).

Кэш — тот же приём, что и в app.core.coverage (JSON на диск, пересчёт по
требованию), но ключ пересчёта другой: у покрытия и статистики это id
последнего прогона, здесь прогонов вообще нет — есть только файлы на диске,
поэтому кэш инвалидируется по mtime_signature() (количество файлов test_*.py
под tests/ и сумма их mtime — дёшево посчитать без парсинга AST на каждый
GET, см. app/routers/sections.py::_ensure_cached)."""
from __future__ import annotations

import ast
import json
from datetime import datetime
from pathlib import Path

from ..config import settings

SECTIONS_DIR = settings.WORKSPACE_DIR / "sections"
_SKIP_DIR_NAMES = {"__pycache__", "allure-results"}


def cache_path(project_name: str) -> Path:
    return SECTIONS_DIR / project_name / "sections.json"


def _skip_dir(name: str) -> bool:
    return name in _SKIP_DIR_NAMES or name.startswith(".")


def _collect_test_function_nodes(path: Path) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return []
    found: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    def _walk(nodes: list[ast.stmt]) -> None:
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                found.append(node)
            elif isinstance(node, ast.ClassDef):
                _walk(node.body)

    _walk(tree.body)
    return found


def _count_test_functions(path: Path) -> int:
    return len(_collect_test_function_nodes(path))


def _is_e2e_marker(decorator: ast.expr) -> bool:
    """`@pytest.mark.e2e` (голый или вызванный, например с доп. `allure.tag`
    рядом — не важно) — единственная форма декоратора маркера, которая
    встречается в auto_tests_vshgu (проверено grep'ом по tests/, нет ни
    `from pytest import mark`, ни `@mark.e2e` на классе)."""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return (
        isinstance(target, ast.Attribute)
        and target.attr == "e2e"
        and isinstance(target.value, ast.Attribute)
        and target.value.attr == "mark"
        and isinstance(target.value.value, ast.Name)
        and target.value.value.id == "pytest"
    )


def _count_e2e_marked_tests(path: Path) -> int:
    """Сколько тестов файла помечены `@pytest.mark.e2e` — сквозные сценарии
    слушателя в auto_tests_vshgu размечены маркером прямо в tests/ui/*, не
    вынесены в отдельную папку (см. docs/plans/2026-10-14_e2e_markers_mission.md
    в auto_tests_vshgu), поэтому псевдо-раздел tests/e2e должен включать и их,
    не только файлы, физически лежащие в tests/e2e (см. discover())."""
    count = 0
    for node in _collect_test_function_nodes(path):
        if any(_is_e2e_marker(d) for d in node.decorator_list):
            count += 1
    return count


def _e2e_virtual_files(tests_root: Path, project_root: Path) -> list[dict]:
    """Файлы псевдо-раздела tests/e2e: физически лежащие в tests/e2e (любые) +
    файлы в tests/api|ui/<область>, где есть хотя бы один `@pytest.mark.e2e`
    (сквозной сценарий слушателя, размеченный маркером на месте, см.
    docstring _count_e2e_marked_tests). Один проход по всему tests/ вместо
    отдельного скана tests/e2e — файл, который и физически в tests/e2e, и
    помечен маркером, не задвоится.

    `name` — путь относительно tests/ (видно, откуда файл: `e2e/lrs/test_x.py`
    — буквально из папки, `ui/aos/user/test_y.py` — подтянут маркером).
    `tests_count` — число тестов с маркером, если есть хоть один, иначе
    (файл буквально в tests/e2e, но без маркера) общее число тестов файла."""
    e2e_dir = tests_root / "e2e"
    files = []
    for path in sorted(tests_root.rglob("test_*.py")):
        rel = path.relative_to(tests_root)
        if any(_skip_dir(part) for part in rel.parts[:-1]):
            continue
        in_e2e_dir = e2e_dir in path.parents
        marked_count = _count_e2e_marked_tests(path)
        if not in_e2e_dir and not marked_count:
            continue
        files.append({
            "name": rel.as_posix(),
            "target": path.relative_to(project_root).as_posix(),
            "tests_count": marked_count or _count_test_functions(path),
        })
    return files


def _scan_files(dir_path: Path, project_root: Path) -> list[dict]:
    """Все test_*.py внутри dir_path (рекурсивно, в т.ч. во вложенных подпапках
    вроде tests/ui/notifications/{admin,user}/), кроме служебных каталогов."""
    files = []
    for path in sorted(dir_path.rglob("test_*.py")):
        if any(_skip_dir(part) for part in path.relative_to(dir_path).parts[:-1]):
            continue
        files.append({
            "name": path.relative_to(dir_path).as_posix(),
            "target": path.relative_to(project_root).as_posix(),
            "tests_count": _count_test_functions(path),
        })
    return files


def _scan_kind(tests_root: Path, project_root: Path, kind: str) -> list[dict]:
    """api/ui -> список областей (подпапок tests/<kind>/<area>). Файлы прямо в
    tests/<kind> (не в подпапке) сюда не попадают — та же граница, что и у
    app.core.stats.discover_section_dirs."""
    kind_dir = tests_root / kind
    areas = []
    if not kind_dir.is_dir():
        return areas
    for sub in sorted(kind_dir.iterdir()):
        if not sub.is_dir() or _skip_dir(sub.name):
            continue
        files = _scan_files(sub, project_root)
        if not files:
            continue
        areas.append({
            "area": sub.name,
            "section": f"{kind}/{sub.name}",
            "target": sub.relative_to(project_root).as_posix(),
            "tests_count": sum(f["tests_count"] for f in files),
            "files": files,
        })
    return areas


def discover(project_path: str) -> dict:
    """Дерево разделов по факту файловой системы: {"kinds": [{"kind", "target",
    "areas": [{"area", "section", "target", "tests_count", "files": [...]}]}]}.
    e2e — один псевдо-раздел без разбивки на области (area=None), см. миссию и
    app.core.stats._section_of_full_name; его файлы — не только буквально
    лежащие в tests/e2e, но и помеченные `@pytest.mark.e2e` где угодно в
    tests/api|ui/* (см. _e2e_virtual_files)."""
    project_root = Path(project_path)
    tests_root = project_root / "tests"
    kinds = []
    for kind in ("api", "ui"):
        areas = _scan_kind(tests_root, project_root, kind)
        if areas:
            kinds.append({"kind": kind, "target": f"tests/{kind}", "areas": areas})

    files = sorted(_e2e_virtual_files(tests_root, project_root), key=lambda f: f["name"])
    if files:
        kinds.append({
            "kind": "e2e",
            "target": "tests/e2e",
            "areas": [{
                "area": None,
                "section": "e2e",
                "target": "tests/e2e",
                "tests_count": sum(f["tests_count"] for f in files),
                "files": files,
            }],
        })
    return {"kinds": kinds}


def mtime_signature(project_path: str) -> list:
    """[количество test_*.py, сумма их mtime] под tests/ — дёшево посчитать
    (только stat(), без чтения/парсинга) и достаточно, чтобы заметить добавление,
    удаление или изменение файла раздела между запросами."""
    tests_root = Path(project_path) / "tests"
    if not tests_root.is_dir():
        return [0, 0.0]
    files = [
        p for p in tests_root.rglob("test_*.py")
        if not any(_skip_dir(part) for part in p.relative_to(tests_root).parts[:-1])
    ]
    return [len(files), round(sum(p.stat().st_mtime for p in files), 3)]


def recalc(project_name: str, project_path: str) -> dict:
    result = {
        "project": project_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mtime_signature": mtime_signature(project_path),
        **discover(project_path),
    }
    out_path = cache_path(project_name)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def load_cached(project_name: str) -> dict | None:
    path = cache_path(project_name)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
