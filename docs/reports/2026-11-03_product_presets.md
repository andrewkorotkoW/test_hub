# Отчёт: пресеты по продуктам в форме запуска (docs/missions/2026-11-03_product_presets.md)

Миссия смержена в `main` отдельными коммитами на каждый раздел плана (логика →
JS-тесты → UI → бот → актуализация смоуков после бота). Эта задача —
документация: README и этот отчёт, код/тесты не менялись.

## Что сделано по пунктам плана

1. **Два ряда пресетов в форме запуска** (`1fed227`, `2cc651b`, `b6cd3ff`,
   `7aeb4db`, `21c2836`, `5a4a9e5`, `c600e50`; `ui/sections-tree-logic.js`,
   `ui/project-sections-picker.js`, `ui/project.html`, `ui/style.css`) —
   ряд «Что» (`LMS`/`Helpdesk`/`LRS`/`Всё`, марка L/H/R + число тестов
   продукта справа) и ряд «Как» (`API`/`UI`/`Smoke`/`E2E`/`Regression`/
   `Mobile`/`Integration`, без изменений в цвете). `presetLeafTargets(data,
   {product, kind})` — продукт сужает множество областей, вид фильтрует
   внутри (как в плане); `REGRESSION_EXCLUDED_AREAS` теперь только
   `INTEGRATION_AREAS` (helpdesk/tickets/lrs из него убраны — у них свои
   кнопки продукта). Гашение (`.dim`, `pointer-events: none`) и сброс вида,
   недоступного для продукта (`kindAvailableForProduct`) — по плану: `Mobile`
   только у LMS/«Всё», `Regression`/`Integration` недоступны у Helpdesk/LRS.
   Строка итога считает тесты, не файлы (`countCheckedByKind`), и теперь
   всегда показывает `· E2E Z`, не только когда он не нулевой.
   **Отклонение от плана, по решению владельца 03.11.2026** (`5a4a9e5`): ряд
   «Что» не получил цвет `--accent`, как было в плане — у VSHGU фирменный
   `--accent` оранжевый и совпадал с цветом кнопки `API` в ряду «Как»;
   продукты вместо этого различаются буквенной маркой L/H/R и нейтральной
   активной заливкой. Также на ревью нашлись и исправлены два CSS-дефекта
   вёрстки по макету (не из плана впрямую, но без них вёрстка не совпадала с
   макетом): правило `.active` по специфичности проигрывало
   `[data-preset]`/`[data-product]` — подпись активной кнопки сливалась с
   фоном (`7aeb4db`, `21c2836`); отступ между маркой/подписью/числом не
   совпадал с макетом (`c600e50`).
2. **Автометка сборки** (`b6cd3ff`, `8f972aa`; `ui/sections-tree-logic.js::
   buildAutoLabel`, `ui/project-run-window.js::autoBuildLabel/computeRunLabel/
   updateBuildChip`) — без ручной метки и без галочки «Мобильный» подставляется
   `"<Продукт>"`/`"<Продукт> · <Вид>"` (`Helpdesk`, `LRS · UI`, `LMS ·
   Regression`); «Всё» без вида — без метки (`null`, как раньше). Галочка
   «Мобильный» всегда даёт `null` от фронта — дефолт «Мобильный (Pixel 7)»
   подставляет бэкенд (`app/core/runner.py:374`, не тронут), чтобы `LMS +
   Mobile` не превратилось в `"LMS · Mobile"`. Чип «Сборка: …» рядом с
   кнопками запуска показывает то же, что реально уйдёт в `submit_run`.
3. **Форма расписания** (`b6cd3ff`) — тот же пикер и те же два ряда, кроме
   кнопки `Mobile` (у расписаний нет флага `mobile`): общий код через
   `createSectionsPicker(..., { mobile: false })`, а не копия разметки, как
   требовал план — иначе смоуки синхронности пресетов (п.5 плана) снова бы
   разошлись после любой правки одной из форм.
4. **Telegram-бот** (`04bc132`, `2fa151d`; `app/tg_bot/handlers.py`,
   `keyboards.py`, `callbacks.py`, `client.py`) — **сделан упрощённый
   вариант, как и допускал план**: добавлен только шаг «продукт»
   (`build_preset_product_keyboard`: LMS/Helpdesk/LRS/Всё) перед списком
   пресетов стенда, **без второго шага «вид»**. Причина (зафиксирована и в
   докстринге `app/tg_bot/__init__.py`, и в README): пресеты стенда — это
   именованные записи БД (`stand_presets`: Smoke/БУК/LPD/API/UI/Всё), а не
   узлы дерева тестов, как в вебе; фильтровать их ещё и по виду внутри
   продукта потребовало бы третьего экрана инлайн-клавиатуры, который не
   укладывается в один шаг — план явно разрешал ограничиться продуктом без
   вида в этом случае («если это тянет переделку клавиатуры больше чем на
   экран — ограничиться продуктом без вида и записать в отчёт»). Реализация:
   `cb_stand` → `build_preset_product_keyboard`; выбор продукта →
   `cb_preset_product` фильтрует пресеты стенда через
   `_preset_matches_product` (парсит сегмент пути после `tests/<kind>/` в
   `preset["target"]` и классифицирует его той же логикой, что `productOf` в
   `ui/sections-tree-logic.js`, продублированной константой `_PRODUCT_AREAS`/
   `_INTEGRATION_AREAS` — импортировать JS в Python код бота смысла не было);
   если под продукт пресетов не нашлось — сообщение «Для продукта «…» нет
   пресетов» с кнопкой назад. Выбранный продукт идёт дальше четвёртым токеном
   `callback_data` (`preset`/`preset_confirm`, `parse_callback` принимает как
   3, так и 4 токена — старый формат без продукта, например у `/stage`,
   остаётся рабочим) и на шаге `cb_preset_confirm` даёт автометку — имя
   продукта (LMS/Helpdesk/LRS), у «Всё» — без метки, вида в метке нет
   (`PRESET_PRODUCT_LABELS`). Команда `/stage <проект> <пресет>` шага
   «продукт» не получила — она ставит пресет по имени напрямую, без
   автометки, как и раньше.
5. **Тесты** (`2cc651b`, `8cd248d`/`3942f8a`, `16356da`/`ebde895`/`464c463`) —
   `tests/js/test_sections_tree_logic.js`: полная матрица product × kind
   `presetLeafTargets`, `productOf`, `kindAvailableForProduct`,
   `buildAutoLabel`, `REGRESSION_EXCLUDED_AREAS` без helpdesk/lrs — **80/80
   passed** (прогнано `node tests/js/test_sections_tree_logic.js`). Четыре
   теста, падавших на `main` с 02.11, обновлены под новую раскладку (не
   удалены): `test_sections_tree_ui_smoke.py::
   test_run_tab_has_seven_presets_including_smoke_e2e_regression_and_mobile`,
   `::test_schedules_tab_has_same_presets_as_run_form_except_mobile`,
   `test_schedules_table_ui_smoke.py::
   test_schedule_presets_match_run_form_except_mobile`,
   `test_mobile_frame_ui.py::
   test_project_js_renders_pixel7_pill_in_feed_and_table_next_to_live`. Новый
   `tests/test_run_auto_label_ui.py` — `computeRunLabel`/`autoBuildLabel`/
   `updateBuildChip` статикой исходника (без браузера). `tests/test_tg_bot.py`
   расширен на шаг «продукт»/фильтр пресетов/автометку бота. Полный прогон —
   см. ниже.
6. **README** (эта задача) — абзац «Пресеты по продуктам» переписан на
   месте старого (искал по «Regression»/«Mobile (Pixel 7)»/«пресеты» —
   устаревший абзац был, но не упоминал Regression/Mobile/Integration
   вовсе: он остался от более ранней миссии, 7 кнопок видов туда так и не
   попали), с новыми title Regression/Integration, правилом гашения,
   автометкой/чипом «Сборка: …» и реальным (упрощённым) поведением
   Telegram-бота в разделе «Ручной прогон на stage». Второго, дублирующего
   абзаца не создавалось.

## Полный прогон тестов

`python3 -m pytest -q -p no:cacheprovider --deselect tests/test_runner_timeout.py`
в foreground: **1403 passed, 3 xfailed**, без ошибок. Node-тесты логики
(`node tests/js/test_sections_tree_logic.js`): **80/80 passed**.

## Изменённые файлы (реализация, не этой задачей)

- `ui/sections-tree-logic.js`, `ui/project-sections-picker.js`,
  `ui/project.html`, `ui/project.js`, `ui/project-setup.js`,
  `ui/project-run-window.js`, `ui/style.css`
- `app/tg_bot/__init__.py`, `handlers.py`, `keyboards.py`, `callbacks.py`,
  `client.py`
- `tests/js/test_sections_tree_logic.js`, `tests/test_sections_tree_ui_smoke.py`,
  `tests/test_schedules_table_ui_smoke.py`, `tests/test_mobile_frame_ui.py`,
  `tests/test_redesign_ui_smoke.py`, `tests/test_run_form_collapse_ui.py`,
  `tests/test_stats_sections_ui_smoke.py`, `tests/test_run_auto_label_ui.py`
  (новый), `tests/test_tg_bot.py`

## Изменённые файлы (эта задача)

`README.md`, `docs/reports/2026-11-03_product_presets.md` (новый).
