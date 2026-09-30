"""Экспорт мокапа v6 (Панель + Светофор) в JPG, 1440px. Запуск: python3 export_screenshots.py"""
import pathlib
from playwright.sync_api import sync_playwright
HERE = pathlib.Path(__file__).resolve().parent
HTML = HERE / "mockups.html"
def main():
    with sync_playwright() as p:
        b = p.chromium.launch(); page = b.new_page(viewport={"width": 1440, "height": 900})
        for theme in ("dark", "light"):
            page.goto(f"file://{HTML}?theme={theme}", wait_until="networkidle")
            page.evaluate("document.querySelector('.ctl').style.display='none'")
            el = page.locator("#f-cov-k"); el.wait_for(state="visible")
            out = HERE / f"coverage-k-panel-traffic-{theme}.jpg"
            el.screenshot(path=str(out), type="jpeg", quality=90); print("saved", out.name)
        b.close()
main()
