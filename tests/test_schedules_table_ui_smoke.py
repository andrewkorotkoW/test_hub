"""Смоук-тесты таблицы «Расписания» (ui/project.html + ui/project-setup.js): колонки
«Цель» / «Следующий запуск» / «Последний результат» рисуются теми же хелперами, что
строка «Прогонов» (HistLogic.targetSummary / fmtStarted, histResultHtml из
ui/project-dashboard.js), а не как «все тесты · #123». Логика самих хелперов покрыта
tests/js/test_runs_history_logic.js; здесь — только разметка и подключение. По образцу
tests/test_dashboard_areas_ui_smoke.py: без браузера, текст исходников через статику.
"""

import pathlib
import re

UI_DIR = pathlib.Path(__file__).resolve().parent.parent / "ui"


async def test_schedules_table_has_next_run_column_between_cron_and_last_result(client):
    resp = await client.get("/project.html")
    assert resp.status_code == 200
    html = resp.text
    head = re.search(r'<tbody id="schedules-rows">', html)
    assert head, "таблица расписаний не найдена"
    thead = html[: head.start()]
    thead = thead[thead.rfind("<thead>"):]
    ths = re.findall(r"<th>(.*?)</th>", thead)
    assert ths == ["", "Стенд", "Маркер", "Цель", "Cron", "Следующий запуск", "Последний результат", ""]


def test_schedule_rows_reuse_history_renderers():
    js = (UI_DIR / "project-setup.js").read_text(encoding="utf-8")
    render = js[js.index("function scheduleTargetHtml") : js.index("async function loadSchedules")]
    # цель — как в истории: первый путь + «+N», полный список в title
    assert "HistLogic.targetSummary(target)" in render
    assert "hist-target-more" in render
    # следующий запуск — из next_run_at, выключенное расписание не притворяется запланированным
    assert "s.next_run_at" in render
    assert "выключено" in render
    assert "HistLogic.fmtStarted(s.next_run_at, now)" in render
    # последний результат — payload last_run: пилюля статуса + полоска/счётчики/Δ истории
    assert "s.last_run" in render
    assert "histResultHtml(r)" in render
    assert 'class="status-pill status-pill-sm ${escapeHtml(r.status)}"' in render
    # ссылка на прогон сохранила класс, на который повешен обработчик openRun
    assert 'class="sched-last-run" data-run-id="${r.id}"' in render
    assert 'colspan="8"' in render
    assert 'colspan="7"' not in render
