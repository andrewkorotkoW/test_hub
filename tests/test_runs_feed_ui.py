"""«Лента прогонов» на дашборде проекта (ui/project-dashboard.js::runsFeedItemHtml,
21.10.2026): вся карточка открывает отчёт (клик и Enter/пробел с клавиатуры), кнопка
«Отчёт» убрана как дублирующая, «Поделиться» — отдельная область справа, клик по ней
окно прогона не открывает."""
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
UI_DIR = REPO_ROOT / "ui"
DASHBOARD_JS = (UI_DIR / "project-dashboard.js").read_text()
STYLE_CSS = (UI_DIR / "style.css").read_text()
TOUR_JS = (UI_DIR / "tour.js").read_text()


def test_feed_card_is_clickable_and_opens_run():
    item = DASHBOARD_JS[DASHBOARD_JS.index("function runsFeedItemHtml(r)"):DASHBOARD_JS.index("function renderRunsFeed(runs)")]
    assert '<div class="runs-feed-item clickable" role="button" tabindex="0" data-run-id="${r.id}"' in item
    assert "runs-feed-report-btn" not in item, "кнопка «Отчёт» дублировала клик по карточке"
    assert 'class="runs-feed-share-btn" data-run-id="${r.id}"' in item
    handler = DASHBOARD_JS[DASHBOARD_JS.index('runsFeedBox.addEventListener("click"'):DASHBOARD_JS.index("// ---------------- известные дефекты")]
    assert handler.index('closest(".runs-feed-share-btn")') < handler.index('closest(".runs-feed-item[data-run-id]")'), \
        "«Поделиться» проверяется раньше карточки и не открывает окно прогона"
    assert "openShareModal(Number(shareBtn.dataset.runId)); return;" in handler
    assert "if (item) openRun(Number(item.dataset.runId));" in handler
    assert 'runsFeedBox.addEventListener("keydown"' in handler and 'ev.key !== "Enter" && ev.key !== " "' in handler


def test_feed_card_styles_and_tour_anchor():
    assert ".runs-feed-item.clickable { cursor: pointer;" in STYLE_CSS
    # при наведении — только фон, без акцентной рамки (замечание владельца 21.10)
    assert ".runs-feed-item.clickable:hover { background: var(--surface-hover); }" in STYLE_CSS
    assert ".runs-feed-item.clickable:focus-visible { outline: 2px solid var(--accent);" in STYLE_CSS
    assert ".runs-feed-actions { border-left: 1px solid var(--border);" in STYLE_CSS
    assert "runs-feed-report-btn" not in TOUR_JS, "тур должен указывать на карточку, а не на убранную кнопку"
