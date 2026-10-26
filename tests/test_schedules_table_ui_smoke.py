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
    assert ths == ["", "Стенд", "Маркер", "Цель", "Cron", "Следующий запуск", "Последний результат", "Уведомления", ""]
    # форма одна на «создать» и «изменить»: заголовок и кнопка «Отмена» меняются из JS
    assert 'id="sched-form-title"' in html
    assert 'id="sched-cancel-btn"' in html


async def test_schedule_presets_match_run_form_except_mobile(client):
    """Пресеты разделов в форме расписания — те же, что в «Запуске» (API/UI/Smoke/E2E/
    Всё/Regression); Mobile намеренно нет: он включает флаг «Мобильный (Pixel 7)»,
    которого у расписаний нет."""
    html = (await client.get("/project.html")).text
    def presets(row_id):
        m = re.search(rf'id="{row_id}">(.*?)</div>', html, re.S)
        assert m, row_id
        return re.findall(r'data-preset="([^"]+)"', m.group(1))
    run_presets = presets("sections-presets-row")
    sched_presets = presets("sched-sections-presets-row")
    assert "mobile" in run_presets
    assert sched_presets == [p for p in run_presets if p != "mobile"]


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
    # telegram-чаты видны в таблице, незавершённый последний прогон подсвечивает строку как в истории
    assert "s.notify_chat_ids" in render
    assert "hist-row-active" in render
    assert 'colspan="9"' in render
    assert 'colspan="8"' not in render and 'colspan="7"' not in render


def test_schedule_edit_mode_reuses_form_and_sends_put():
    js = (UI_DIR / "project-setup.js").read_text(encoding="utf-8")
    assert 'class="sched-edit-btn" data-id="${s.id}"' in js
    edit = js[js.index("function enterScheduleEdit") : js.index("async function loadSchedules")]
    # форма заполняется из расписания: cron -> время + дни, цель -> ручной ввод, чаты
    assert "cronToForm(s.cron)" in edit
    assert 'schedTargetInput.value = s.target === "all" ? "" : s.target' in edit
    assert '(s.notify_chat_ids || []).join(", ")' in edit
    assert 'schedCreateBtn.textContent = "Сохранить"' in edit
    assert "schedCancelBtn.hidden = false" in edit
    # отправка: PUT в режиме правки, POST с enabled: true при создании
    submit = js[js.index("schedCreateBtn.addEventListener") :]
    assert "schedules/${editingScheduleId}`, { method: \"PUT\"" in submit
    assert 'method: "POST", json: { ...body, enabled: true }' in submit
    assert "exitScheduleEdit();" in submit
