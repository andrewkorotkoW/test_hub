"""Экспорт мокапов вкладки «Тест-кейсы» в JPG (1440px, Playwright).

Запуск: .venv/bin/python3 docs/missions/testcases/export_screenshots.py
Открывает mockups.html файлом (file://), переключает тему через query-параметр
(theme), делает screenshot секций #v1/#v2 (весь вариант: mock-head с h2 +
рамка макета).
"""
import pathlib

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
HTML = HERE / "mockups.html"

# (id секции, файл-имя без темы)
TARGETS = [
    ("v1", "testcases-tree"),
    ("v2", "testcases-table"),
]
THEMES = ["dark", "light"]


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        for theme in THEMES:
            url = f"file://{HTML}?theme={theme}"
            page.goto(url, wait_until="networkidle")
            # .ctl — верхняя панель (position:sticky) — при скролле "прилипает"
            # и попадает в скриншот секции поверх заголовка варианта (h2),
            # поэтому на время снимка убираем её из потока.
            page.evaluate("document.querySelector('.ctl').style.display='none'")
            for section_id, basename in TARGETS:
                el = page.locator(f"#{section_id}")
                el.wait_for(state="visible")
                out = HERE / f"{basename}-{theme}.jpg"
                el.screenshot(path=str(out), type="jpeg", quality=90)
                print("saved", out.name)
        browser.close()


if __name__ == "__main__":
    main()
