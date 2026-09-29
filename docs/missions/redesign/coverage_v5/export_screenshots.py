"""Экспорт финального мокапа карты покрытия v5 в JPG (1440px, Playwright).

Адаптировано из docs/missions/redesign/coverage_v4/export_screenshots.py: один
вариант вместо двух (J/K из предыдущего этапа владелец отклонил в пользу
раскладки sketch_approved.svg), поэтому TARGETS сведён к одному кадру.

Запуск: python3 export_screenshots.py
"""
import pathlib

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
HTML = HERE / "mockups.html"

FRAME_ID = "f-coverage"
BASENAME = "coverage-j-scheme"
THEMES = ["dark", "light"]


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        for theme in THEMES:
            url = f"file://{HTML}?theme={theme}"
            page.goto(url, wait_until="networkidle")
            # .ctl — верхняя панель (position:sticky) — при скролле "прилипает"
            # и попадает в скриншот элемента поверх контента, поэтому её
            # на время снимка прячем.
            page.evaluate("document.querySelector('.ctl').style.display='none'")
            el = page.locator(f"#{FRAME_ID}")
            el.wait_for(state="visible")
            out = HERE / f"{BASENAME}-{theme}.jpg"
            el.screenshot(path=str(out), type="jpeg", quality=90)
            print("saved", out.name)
        browser.close()


if __name__ == "__main__":
    main()
