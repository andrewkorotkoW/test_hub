"""Экспорт блоков «как предлагаем» из mockups.html в JPG (1440px, Playwright).

Запуск: python3 export_proposal_screenshots.py
Открывает mockups.html файлом (file://), переключает раздел/тему через
query-параметры (page/theme), делает screenshot блока .frame (id f-<page>) —
именно того элемента, что содержит макет-предложение на всю ширину. По образцу
export_screenshots.py из redesign/run_window и redesign/testcases.
"""
import pathlib

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
HTML = HERE / "mockups.html"

# (page, frame_id, файл-имя без темы)
TARGETS = [
    ("projects", "f-projects", "projects-proposal"),
    ("dashboard", "f-dashboard", "dashboard-proposal"),
    ("history", "f-history", "history-proposal"),
    ("flaky", "f-flaky", "flaky-proposal"),
    ("xfail", "f-xfail", "xfail-proposal"),
    ("schedules", "f-schedules", "schedules-proposal"),
    ("testcases", "f-testcases", "testcases-proposal"),
    ("stats", "f-stats", "stats-proposal"),
    ("sidebar", "f-sidebar", "sidebar-proposal"),
]
THEMES = ["dark", "light"]


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        for section, frame_id, basename in TARGETS:
            for theme in THEMES:
                url = f"file://{HTML}?page={section}&theme={theme}"
                page.goto(url, wait_until="networkidle")
                # .ctl — верхняя панель (position:sticky) — при скролле "прилипает"
                # и попадает в скриншот элемента поверх контента, поэтому её
                # на время снимка прячем.
                page.evaluate("document.querySelector('.ctl').style.display='none'")
                el = page.locator(f"#{frame_id}")
                el.wait_for(state="visible")
                out = HERE / f"{basename}-{theme}.jpg"
                el.screenshot(path=str(out), type="jpeg", quality=90)
                print("saved", out.name)
        browser.close()


if __name__ == "__main__":
    main()
