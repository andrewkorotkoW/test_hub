"""TH_ALLURE_BIN: явный путь к allure CLI (app/core/allure_report.py::resolve_allure_bin)
и порядок поиска, если он не задан — PATH, затем типичные каталоги ручной установки
(см. раздел «Allure CLI» в README). Без этого сервис под launchd/systemd с урезанным
PATH молча не находит allure и отдаёт 404 на публичной ссылке (см. tests/test_share.py::
test_public_share_allure_without_cli_reports_unavailable для заглушки вместо 404).
"""
import os
import stat

from app.config import settings
from app.core import allure_report


def _make_executable(path):
    path.write_text("#!/bin/sh\necho fake-allure\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def test_th_allure_bin_defaults_to_empty(monkeypatch):
    monkeypatch.delenv("TH_ALLURE_BIN", raising=False)
    assert settings.TH_ALLURE_BIN == ""


def test_resolve_allure_bin_prefers_configured_path(tmp_path, monkeypatch):
    fake = tmp_path / "allure"
    _make_executable(fake)
    monkeypatch.setattr(settings, "TH_ALLURE_BIN", str(fake))
    monkeypatch.setattr(allure_report.shutil, "which", lambda name: "/should/not/be/used")

    assert allure_report.resolve_allure_bin() == str(fake)


def test_resolve_allure_bin_rejects_configured_path_that_does_not_exist(monkeypatch, caplog):
    monkeypatch.setattr(settings, "TH_ALLURE_BIN", "/no/such/allure/binary")

    with caplog.at_level("WARNING"):
        result = allure_report.resolve_allure_bin()

    assert result is None
    assert "TH_ALLURE_BIN" in caplog.text


def test_resolve_allure_bin_falls_back_to_path_when_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "TH_ALLURE_BIN", "")
    monkeypatch.setattr(allure_report.shutil, "which", lambda name: "/usr/bin/allure")

    assert allure_report.resolve_allure_bin() == "/usr/bin/allure"


def test_resolve_allure_bin_falls_back_to_extra_dirs(tmp_path, monkeypatch):
    fake_dir = tmp_path / "homebrew_bin"
    fake_dir.mkdir()
    fake = fake_dir / "allure"
    _make_executable(fake)

    monkeypatch.setattr(settings, "TH_ALLURE_BIN", "")
    monkeypatch.setattr(allure_report.shutil, "which", lambda name: None)
    monkeypatch.setattr(allure_report, "EXTRA_SEARCH_DIRS", (str(fake_dir),))

    assert allure_report.resolve_allure_bin() == str(fake)


def test_resolve_allure_bin_none_and_logs_searched_locations(monkeypatch, caplog):
    monkeypatch.setattr(settings, "TH_ALLURE_BIN", "")
    monkeypatch.setattr(allure_report.shutil, "which", lambda name: None)
    monkeypatch.setattr(allure_report, "EXTRA_SEARCH_DIRS", (str(os.path.join("/", "no", "such", "dir")),))

    with caplog.at_level("WARNING"):
        result = allure_report.resolve_allure_bin()

    assert result is None
    assert "PATH" in caplog.text
    assert "TH_ALLURE_BIN" in caplog.text


def test_allure_cli_available_reflects_resolve(monkeypatch):
    monkeypatch.setattr(allure_report, "resolve_allure_bin", lambda: None)
    assert allure_report.allure_cli_available() is False

    monkeypatch.setattr(allure_report, "resolve_allure_bin", lambda: "/usr/bin/allure")
    assert allure_report.allure_cli_available() is True


def test_ensure_static_report_uses_resolved_bin(tmp_path, monkeypatch):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    report_dir = tmp_path / "report"
    fake = tmp_path / "fake-allure"
    _make_executable(fake)

    seen_argv = {}

    def fake_run(argv, **kwargs):
        seen_argv["argv"] = argv
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "index.html").write_text("<html></html>")

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(settings, "TH_ALLURE_BIN", str(fake))
    monkeypatch.setattr(allure_report.subprocess, "run", fake_run)

    assert allure_report.ensure_static_report(results_dir, report_dir) is True
    assert seen_argv["argv"][0] == str(fake)


def test_ensure_static_report_false_when_bin_not_resolved(tmp_path, monkeypatch):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    report_dir = tmp_path / "report"

    monkeypatch.setattr(allure_report, "resolve_allure_bin", lambda: None)

    assert allure_report.ensure_static_report(results_dir, report_dir) is False
    assert not (report_dir / "index.html").exists()
