import pathlib
from playwright.sync_api import sync_playwright
HERE=pathlib.Path(__file__).resolve().parent; HTML=HERE/'mockups.html'
with sync_playwright() as p:
    b=p.chromium.launch(); page=b.new_page(viewport={'width':1200,'height':900})
    for theme in ('dark','light'):
        page.goto(f'file://{HTML}?theme={theme}', wait_until='networkidle'); page.wait_for_timeout(500)
        page.evaluate("document.querySelector('.ctl').style.display='none'")
        for v in ('a','c','d','e'):
            el=page.locator(f'#v{v} .frame'); el.screenshot(path=str(HERE/f'areas-{v}-{theme}.jpg'), type='jpeg', quality=90); print('saved', f'areas-{v}-{theme}.jpg')
    b.close()
