# Миссия: пресеты по продуктам в форме запуска (LMS / Helpdesk / LRS) — два ряда

Записано 03.11.2026 по решению владельца: «вариант A, делай миссию». Кликабельный макет обоих
вариантов — `docs/missions/redesign/product_presets/mockups.html` (вариант A одобрен, вариант B
отклонён). Делать по макету, не выдумывать другую раскладку.

## Зачем

У платформы три продукта: LMS (портал), Helpdesk и LRS (OpenLRS). Все три есть на develop и на
остальных стендах. Сейчас кнопка «Всё» запускает всё подряд, а области `helpdesk`, `tickets` и `lrs`
зашиты в `REGRESSION_EXCLUDED_AREAS` (`ui/sections-tree-logic.js:60`) и потому попадают в пресет
«Integration» вместе с внешними интеграциями (ai_chat, cas, buk, mts_link, p2p). Из-за этого один
прогон смешивает падения трёх систем (прогон #112 «Integration» на 2066: ai_chat + helpdesk), а
дельта в истории и флаки сравнивают несравнимое. Разделение по продукту чинит это у корня.

## Что сделать

### 1. Два ряда пресетов в форме запуска (`ui/project.html:174`, `ui/project-sections-picker.js`, `ui/sections-tree-logic.js`)

- Ряд **«Что»** (продукт): `LMS`, `Helpdesk`, `LRS`, `Всё`. У каждой кнопки, кроме «Всё», слева
  буквенная марка (L / H / R) и справа число тестов продукта моноширинным (из дерева, пересчитывать
  при загрузке). Цвет ряда — `--accent` (цвет проекта), не статусные цвета.
- Ряд **«Как»** (вид): существующие `API`, `UI`, `Smoke`, `E2E`, `Regression`, `Mobile`,
  `Integration` — без изменений в цветах (`ui/style.css:626-635`).
- Подписи рядов «Что» / «Как» — `.label` слева (grid `52px 1fr`, как в макете), на узких экранах
  (≤640px) ряды в столбик.
- Логика в `ui/sections-tree-logic.js` (чистая, без DOM, node v12 — без `??`/`?.`):
  - `PRODUCT_AREAS = {helpdesk: ["helpdesk", "tickets"], lrs: ["lrs"]}`,
    `INTEGRATION_AREAS = ["ai_chat", "cas", "buk", "mts_link", "p2p"]`; `productOf(area)` →
    `helpdesk | lrs | integration | lms`.
  - `REGRESSION_EXCLUDED_AREAS` = только `INTEGRATION_AREAS` (helpdesk/tickets/lrs из него убрать).
  - `presetLeafTargets(data, {product, kind})`: продукт задаёт множество областей (`all` — все;
    `lms` — всё, что не helpdesk/lrs/integration), вид фильтрует внутри: `api/ui/e2e` — по kind,
    `mobile` — область `mobile`, `regression` — без INTEGRATION_AREAS, `integration` — только
    INTEGRATION_AREAS, `smoke` — маркер (как сейчас, файлы не фильтрует).
  - Правила гашения кнопок вида при выбранном продукте (как в макете, класс `.dim`,
    `pointer-events: none`): `Mobile` доступен только при `LMS`/`Всё`; `Regression` и
    `Integration` недоступны при `Helpdesk`/`LRS`. Если выбранный вид стал недоступен — сбросить.
- Состояние формы: продукт (по умолчанию `all`) + вид (по умолчанию нет). Клик по продукту не
  сбрасывает вид, кроме случая гашения; клик по тому же виду снимает его. После выбора дерево
  перерисовывается с выставленными чекбоксами, ручная донастройка остаётся возможной (как сейчас).
- Строка итога «Выбрано: N тестов · API x · UI y · E2E z» — числа тестов, не файлов (сейчас
  «0 файлов · API 0 · UI 0» смешивает единицы).

### 2. Автоматическая метка сборки (`ui/project-run-window.js::submitRun`, `app/core/runner.py::submit_run`)

- Если пользователь не ввёл `label`, форма подставляет `"<Продукт>"` или `"<Продукт> · <Вид>"`
  (`Helpdesk`, `LRS · UI`, `LMS · Regression`); при `Всё` без вида — метки нет (как сейчас).
  Mobile по-прежнему даёт «Мобильный (Pixel 7)» (`runner.py:374`) — при `LMS + Mobile` метка
  «Мобильный (Pixel 7)», не «LMS · Mobile» (не ломать фильтр истории и тесты мобильного).
- Чип «Сборка: …» рядом с кнопкой запуска показывает, что подставится (как в макете). Подстановка
  — на фронте, чтобы владелец видел её до запуска; бэкенд не меняется, кроме п.4.
- В ленте и истории прогонов такие метки работают через существующий фильтр «сборка» —
  ничего нового, проверить, что цветной тег «сборка» (коммит 73f9930) их подхватывает.

### 3. Форма расписания (`ui/project.html:373`, тот же `sections-picker`)

Те же два ряда, но без `Mobile` (у расписаний нет флага mobile). Общий код с формой запуска:
пресеты рендерятся одной функцией с параметром `{mobile: false}`, а не копией разметки — иначе
тесты синхронности пресетов (`tests/test_schedules_table_ui_smoke.py`,
`tests/test_sections_tree_ui_smoke.py`) снова разъедутся.

### 4. Telegram-бот (`app/tg_bot`)

Меню запуска по пресетам (`cb_preset`, `build_preset_keyboard`) — добавить продукт первым шагом
(LMS / Helpdesk / LRS / Всё), затем вид, как в вебе; та же автометка. Если это тянет переделку
клавиатуры больше чем на экран — ограничиться продуктом без вида и записать в отчёт.

### 5. Тесты

- `tests/js/test_sections_tree_logic.js` (или существующий файл логики дерева): `productOf`,
  `presetLeafTargets` для всех сочетаний продукт × вид, гашение, `REGRESSION_EXCLUDED_AREAS` без
  helpdesk/lrs; `Всё` без вида == прежний полный набор; `LMS + Regression` == прежний Regression
  минус ничего (helpdesk/lrs уже не в LMS).
- Четыре теста, падающих на main с 02.11 (`tests/test_sections_tree_ui_smoke.py::
  test_run_tab_has_seven_presets_including_smoke_e2e_regression_and_mobile`,
  `::test_schedules_tab_has_same_presets_as_run_form_except_mobile`,
  `tests/test_schedules_table_ui_smoke.py::test_schedule_presets_match_run_form_except_mobile`,
  `tests/test_mobile_frame_ui.py::test_project_js_renders_pixel7_pill_in_feed_and_table_next_to_live`)
  — обновить под новую раскладку, не удалять.
- Автометка: `submitRun` с продуктом `helpdesk` и видом `api` шлёт `label: "Helpdesk · API"`;
  с `LMS + Mobile` — «Мобильный (Pixel 7)»; с `Всё` без вида — `null`.
- Smoke страницы: оба ряда есть в форме запуска, в расписании нет `Mobile`.

### 6. README — абзац «Пресеты по продуктам», обновить подписи title у Regression/Integration
(«без внешних интеграций: ai_chat, CAS, БУК, МТС Линк, P2P»).

## Правила

Ветка от `main`, `pytest -q -p no:cacheprovider --deselect tests/test_runner_timeout.py` зелёный в
foreground (без фоновых pytest!), JS-логика без DOM в `ui/*-logic.js` с node-тестом. Контракт
плагина проекта тестов, API прогонов (`RunCreate`) и схему покрытия не трогать. Отчёт —
`docs/reports/2026-11-03_product_presets.md`.
