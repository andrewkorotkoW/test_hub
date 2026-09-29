"""Экспорт мокапов окна прогона + карты покрытия в JPG (1440px, Playwright).

Запуск: python3 export_screenshots.py
Открывает mockups.html файлом (file://), переключает вариант/тему через
query-параметры (page/variant/theme), делает screenshot блока .frame
(id f-<key>) — именно того элемента, что содержит мокап на весь экран.
"""
import pathlib

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
HTML = HERE / "mockups.html"

# (page, variant, frame_id, файл-имя без темы)
TARGETS = [
    ("run", "a", "f-run-a", "run-a-filmstrip"),
    ("run", "b", "f-run-b", "run-b-split"),
    ("run", "c", "f-run-c", "run-c-terminal"),
    ("coverage", "a", "f-cov-a", "coverage-a-tree"),
    ("coverage", "b", "f-cov-b", "coverage-b-heatmap"),
    ("coverage", "c", "f-cov-c", "coverage-c-sunburst"),
]
THEMES = ["dark", "light"]


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        for section, variant, frame_id, basename in TARGETS:
            for theme in THEMES:
                url = f"file://{HTML}?page={section}&variant={variant}&theme={theme}"
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
