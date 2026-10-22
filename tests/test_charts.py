"""Юнит-тесты app/core/charts.py — build_report_png/build_trend_png.

Модуль чистый (matplotlib, backend Agg): без сети и без БД, поэтому тесты
вызывают функции напрямую на сконструированных структурах run/history/results,
без ASGI-клиента и фикстур проекта из conftest.py.
"""

from datetime import datetime, timedelta

import pytest

from app.core.charts import build_report_png, build_trend_png

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

try:
    from PIL import Image

    HAS_PIL = True
except ImportError:  # pragma: no cover - PIL уже есть в зависимостях (matplotlib)
    HAS_PIL = False


def _assert_valid_png(data: bytes) -> None:
    assert isinstance(data, bytes)
    assert len(data) > 0
    assert data.startswith(PNG_SIGNATURE)
    if HAS_PIL:
        import io

        img = Image.open(io.BytesIO(data))
        img.verify()


def _run(counts, **overrides):
    base = {
        "id": 1,
        "project": "demo",
        "stand": "stage",
        "marker": "smoke",
        "status": "failed" if counts.get("failed") or counts.get("broken") else "passed",
        "started": "2026-09-01T10:00:00",
        "finished": "2026-09-01T10:05:00",
        "duration": 300,
        "counts": counts,
    }
    base.update(overrides)
    return base


def _history_item(i, passed=3, failed=2, started=None):
    return {
        "id": i,
        "started": started or (datetime(2026, 9, 1) + timedelta(days=i)).isoformat(),
        "counts": {"passed": passed, "failed": failed, "broken": 0, "skipped": 0},
    }


def _results(n=5, with_duration=True):
    tests = []
    for i in range(n):
        status = "failed" if i % 2 == 0 else "passed"
        tests.append(
            {
                "name": f"tests/test_mod_{i}.py::test_case_{i}",
                "status": status,
                "duration": float(i + 1) if with_duration else None,
                "message": "boom" if status == "failed" else None,
            }
        )
    return tests


class TestBuildReportPng:
    def test_normal_run(self):
        run = _run({"passed": 7, "failed": 2, "broken": 1, "skipped": 1})
        history = [_history_item(i) for i in range(4)]
        results = _results(6, with_duration=True)

        data = build_report_png(run, history, results)

        _assert_valid_png(data)

    def test_empty_history(self):
        run = _run({"passed": 5, "failed": 0, "broken": 0, "skipped": 0})
        results = _results(3, with_duration=True)

        data = build_report_png(run, [], results)

        _assert_valid_png(data)

    def test_no_failures(self):
        run = _run({"passed": 8, "failed": 0, "broken": 0, "skipped": 2})
        history = [_history_item(i, passed=8, failed=0) for i in range(3)]
        results = [
            {"name": "tests/test_a.py::test_ok", "status": "passed", "duration": 1.2, "message": None},
            {"name": "tests/test_b.py::test_ok2", "status": "passed", "duration": 0.5, "message": None},
        ]

        data = build_report_png(run, history, results)

        _assert_valid_png(data)

    def test_results_without_duration_falls_back_to_failed_modules(self):
        run = _run({"passed": 3, "failed": 4, "broken": 0, "skipped": 0})
        history = [_history_item(i) for i in range(2)]
        results = [
            {"name": "tests/test_mod_a.py::test_x", "status": "failed", "duration": None, "message": "x"},
            {"name": "tests/test_mod_a.py::test_y", "status": "broken", "duration": None, "message": "y"},
            {"name": "tests/test_mod_b.py::test_z", "status": "passed", "duration": None, "message": None},
        ]

        data = build_report_png(run, history, results)

        _assert_valid_png(data)

    def test_empty_run_zero_counts(self):
        run = _run({"passed": 0, "failed": 0, "broken": 0, "skipped": 0})
        run["status"] = None
        run["started"] = None
        run["finished"] = None
        run["duration"] = None

        data = build_report_png(run, [], [])

        _assert_valid_png(data)

    def test_missing_run_fields_do_not_raise(self):
        # Ни project/stand/marker, ни counts вовсе нет в словаре.
        data = build_report_png({}, [], [])

        _assert_valid_png(data)

    def test_light_theme_with_causes_label_and_rerun_duplicates(self):
        """Светлый макет (22.10.2026): фон страницы --bg светлой темы, причины в шапке,
        сборка в заголовке, топ-10 по финальной попытке (дубликаты по реранам не
        дают двух строк), подписи по nodeid."""
        run = _run({"passed": 4, "failed": 1, "broken": 0, "skipped": 0}, label="Смоук", duration=1382)
        history = [_history_item(i) for i in range(12)]
        results = [
            {"name": "tests.api.test_cas#test_sync", "nodeid": "tests/api/test_cas.py::test_sync",
             "status": "failed", "duration": 277.0, "stop_ts": "2026-10-19T22:01:00"},
            {"name": "tests.api.test_cas#test_sync", "nodeid": "tests/api/test_cas.py::test_sync",
             "status": "passed", "duration": 250.0, "stop_ts": "2026-10-19T22:06:00"},
            {"name": "tests.ui.test_login#test_ok", "status": "passed", "duration": 53.5, "stop_ts": None},
        ]
        causes = {"throttling": 1, "session": 0, "stand": 0, "code": 0, "total": 1}

        wide = build_report_png(run, history, results, causes, layout="wide")
        mobile = build_report_png(run, history, results, causes)  # по умолчанию — портрет под телефон

        _assert_valid_png(wide)
        _assert_valid_png(mobile)
        if HAS_PIL:
            import io

            img = Image.open(io.BytesIO(wide)).convert("RGB")
            assert img.size == (1200, 1400)
            assert img.getpixel((2, 2)) == (0xF5, 0xF6, 0xF8)  # --bg светлой темы, не #10142a
            assert Image.open(io.BytesIO(mobile)).size == (1080, 1920)

    def test_mobile_layout_handles_many_tests_and_empty_data(self):
        results = [
            {"name": f"tests.ui.test_very_long_module_name_{i}.TestSuite#test_case_with_long_name_{i}",
             "status": "passed", "duration": float(10 * i + 1)}
            for i in range(30)
        ]
        _assert_valid_png(build_report_png(_run({"passed": 30}), [], results))
        _assert_valid_png(build_report_png({}, [], []))
        _assert_valid_png(build_report_png(_run({"passed": 0, "failed": 2}), [_history_item(1)], [
            {"name": "tests/test_a.py::test_x", "status": "failed", "duration": None},
        ]))


class TestBuildTrendPng:
    def test_empty_history(self):
        data = build_trend_png([])

        _assert_valid_png(data)

    def test_large_history_capped_at_30(self):
        history = [_history_item(i, passed=i, failed=i % 3) for i in range(45)]

        data = build_trend_png(history)

        _assert_valid_png(data)

    @pytest.mark.parametrize("n", [1, 11, 30])
    def test_various_sizes(self, n):
        history = [_history_item(i) for i in range(n)]

        data = build_trend_png(history)

        _assert_valid_png(data)
