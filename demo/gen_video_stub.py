"""Генератор коротких webm-заглушек видео для демо-прогона (docs/missions/
2026-10-01_live_stream.md, раздел «Демо-проект»): demo/tests не шлёт кадры и видео
через плагин auto_tests_vshgu (его здесь просто нет), поэтому вкладка «Видео» окна
прогона у проекта Demo показывается через готовые заглушки — их app/core/demo_video.py
подставляет 1-2 пройденным тестам завершившегося прогона Demo.

Кодирует настоящий проигрываемый webm через запись видео Playwright (уже используется
в проекте для скриншотов, см. docs/missions/testcases/export_screenshots.py): Chromium
рендерит статичную страницу, видео пишет собственный бандл ffmpeg плагина — системный
ffmpeg/vpxenc не нужен, а результат честно играбелен в браузере (не суррогатный файл).

Запуск: python3 demo/gen_video_stub.py [--force]
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ASSETS_DIR = Path(__file__).resolve().parent / "assets" / "video"
DURATION_SECONDS = 2.4
VIEWPORT = {"width": 320, "height": 180}
MAX_COMMIT_BYTES = 200 * 1024

# Токены DESIGN.md (тёмная тема + статус passed) — цвета не придуманы, а взяты оттуда.
_BG = "#0f1223"
_TEXT = "#e7e9f5"
_ACCENT = "#22c55e"
_FONT = "Golos Text, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"

STUBS = [
    ("stub_1.webm", "test_hub demo · запись теста"),
    ("stub_2.webm", "test_hub demo · заглушка №2"),
]


def _page_html(caption: str) -> str:
    return (
        f"<html><body style=\"margin:0;background:{_BG};color:{_TEXT};"
        f"font-family:'{_FONT}';display:flex;align-items:center;justify-content:center;"
        f"height:{VIEWPORT['height']}px;flex-direction:column;gap:8px\">"
        f"<div style=\"width:10px;height:10px;border-radius:50%;background:{_ACCENT}\"></div>"
        f"<div style=\"font-size:13px\">{caption}</div>"
        f"</body></html>"
    )


def _generate_one(name: str, caption: str, force: bool) -> None:
    dest = ASSETS_DIR / name
    if dest.is_file() and not force:
        print(f"{dest} уже есть, пропуск (--force для перегенерации)")
        return

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                viewport=VIEWPORT,
                record_video_dir=str(ASSETS_DIR),
                record_video_size=VIEWPORT,
            )
            page = context.new_page()
            page.set_content(_page_html(caption))
            video = page.video
            time.sleep(DURATION_SECONDS)
            context.close()
            generated = Path(video.path())
        finally:
            browser.close()

    generated.replace(dest)
    size = dest.stat().st_size
    print(f"{dest} готово, {size / 1024:.1f} КБ")
    if size > MAX_COMMIT_BYTES:
        raise SystemExit(f"{dest}: {size / 1024:.1f} КБ превышает лимит 200 КБ на бинарник в git")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="перегенерировать, даже если файлы уже есть")
    args = parser.parse_args()
    for name, caption in STUBS:
        _generate_one(name, caption, args.force)


if __name__ == "__main__":
    main()
