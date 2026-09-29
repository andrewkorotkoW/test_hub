"""Экспорт скриншотов «как сейчас» живого test_hub (1440px, Playwright).

Запуск (сервер test_hub уже должен быть поднят на BASE_URL, вход qa/qa):
    python3 docs/missions/redesign/visual_audit/export_screenshots.py

Логинится как qa/qa через UI-форму (ui/index.html), затем последовательно
открывает страницы/вкладки из TARGETS, переключает тему через localStorage
(testhub-theme, см. ui/common.js) и сохраняет JPG в before/.
"""
import pathlib

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "before"
BASE_URL = "http://127.0.0.1:8711"

# (файл-имя, url, ожидаемый селектор для ожидания прогрузки данных)
TARGETS = [
    ("projects", "/projects.html", "body"),
    ("project-dashboard-vshgu", "/project.html?name=VSHGU#dashboard", "[data-tab-panel=dashboard]"),
    ("project-run-vshgu", "/project.html?name=VSHGU#run", "[data-tab-panel=run]"),
    ("project-schedules-vshgu", "/project.html?name=VSHGU#schedules", "[data-tab-panel=schedules]"),
    ("project-history-vshgu", "/project.html?name=VSHGU#history", "[data-tab-panel=history]"),
    ("project-flaky-vshgu", "/project.html?name=VSHGU#flaky", "[data-tab-panel=flaky]"),
    ("project-dashboard-demo", "/project.html?name=Demo#dashboard", "[data-tab-panel=dashboard]"),
    ("xfail-vshgu", "/xfail.html?name=VSHGU", "body"),
    ("xfail-demo", "/xfail.html?name=Demo", "body"),
    ("coverage-vshgu", "/coverage.html?name=VSHGU", "body"),
    ("stats-vshgu", "/stats.html?name=VSHGU", "body"),
]
THEMES = ["dark", "light"]


def login(page):
    page.goto(f"{BASE_URL}/index.html", wait_until="networkidle")
    page.fill("#login", "qa")
    page.fill("#password", "qa")
    page.click("button[type=submit]")
    page.wait_for_url(f"{BASE_URL}/projects.html", timeout=10000)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        login(page)
        for theme in THEMES:
            page.evaluate(f"localStorage.setItem('testhub-theme', '{theme}')")
            for basename, path, wait_sel in TARGETS:
                page.goto(f"{BASE_URL}{path}", wait_until="networkidle")
                try:
                    page.wait_for_selector(wait_sel, timeout=5000)
                except Exception:
                    pass
                page.wait_for_timeout(500)
                out = OUT / f"{basename}-{theme}.jpg"
                page.screenshot(path=str(out), type="jpeg", quality=90, full_page=True)
                print("saved", out.name)
        browser.close()


if __name__ == "__main__":
    main()
