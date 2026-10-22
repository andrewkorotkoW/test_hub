"""Маркеры pytest проекта из его конфигурации — pytest.ini / setup.cfg / tox.ini
(`markers =` в секции [pytest] или [tool:pytest]) и pyproject.toml
(`[tool.pytest.ini_options] markers = [...]`). Нужны боту (клавиатура «набор тестов»
строится по реальным маркерам проекта, а не по вшитым Smoke/API/UI — замечание
владельца 22.10.2026) и форме запуска. Чистые функции, без БД и сети."""
from __future__ import annotations

import configparser
import re
import tomllib
from pathlib import Path

# «env(name): описание» — параметризованные маркеры запускать через -m нельзя,
# в список для кнопок не попадают.
_MARKER_LINE_RE = re.compile(r"^\s*([A-Za-z_][\w]*)(\([^)]*\))?\s*(?::\s*(.*))?$")

INI_FILES = (("pytest.ini", "pytest"), ("setup.cfg", "tool:pytest"), ("tox.ini", "pytest"))


def _parse_marker_lines(lines: list[str]) -> list[dict]:
    markers: list[dict] = []
    seen: set[str] = set()
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        match = _MARKER_LINE_RE.match(line)
        if not match or match.group(2):
            continue
        name = match.group(1)
        if name in seen:
            continue
        seen.add(name)
        markers.append({"name": name, "description": (match.group(3) or "").strip()})
    return markers


def _from_ini(path: Path, section: str) -> list[dict] | None:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, OSError):
        return None
    if not parser.has_option(section, "markers"):
        return None
    return _parse_marker_lines(parser.get(section, "markers").splitlines())


def _from_pyproject(path: Path) -> list[dict] | None:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    options = data.get("tool", {}).get("pytest", {}).get("ini_options", {})
    markers = options.get("markers")
    if isinstance(markers, str):
        return _parse_marker_lines(markers.splitlines())
    if isinstance(markers, list):
        return _parse_marker_lines([str(m) for m in markers])
    return None


def read_markers(project_path: str) -> list[dict]:
    """[{"name": "smoke", "description": "Smoke tests"}, ...] в порядке объявления;
    первый найденный конфиг с `markers` выигрывает (как у самого pytest: pytest.ini
    приоритетнее pyproject/tox/setup.cfg). Нет конфига или маркеров — []."""
    root = Path(project_path)
    for filename, section in INI_FILES[:1]:
        found = _from_ini(root / filename, section)
        if found is not None:
            return found
    found = _from_pyproject(root / "pyproject.toml")
    if found is not None:
        return found
    for filename, section in INI_FILES[1:]:
        found = _from_ini(root / filename, section)
        if found is not None:
            return found
    return []
