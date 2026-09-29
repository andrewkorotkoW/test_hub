"""Экспорт мокапов карты покрытия v3 в JPG (1440px, Playwright).

Адаптировано из docs/missions/redesign/coverage_v2/export_screenshots.py под
варианты этого каталога (f/g вместо d/e).

Запуск: python3 export_screenshots.py
"""
import pathlib

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
HTML = HERE / "mockups.html"

# (variant, frame_id, файл-имя без темы)
TARGETS = [
    ("f", "f-cov-f", "coverage-f-onemap"),
    ("g", "f-cov-g", "coverage-g-traffic"),
]
THEMES = ["dark", "light"]


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        for variant, frame_id, basename in TARGETS:
            for theme in THEMES:
                url = f"file://{HTML}?v={variant}&theme={theme}"
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
