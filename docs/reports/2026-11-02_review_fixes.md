# Отчёт: пять правок по итогам ревью всех страниц (docs/missions/2026-11-02_review_fixes.md)

Миссия смержена в `main` тремя частями (1+2 → 3+4 → 5), каждая с отдельным
коммитом тестов сразу после реализации. Эта задача — документация: README и
этот отчёт, код и тесты не менялись.

## Что сделано по пунктам миссии

1. **Последний прогон для KPI/дашборда без `cancelled`** (`ec929db`,
   `app/core/stats.py::_latest_full_run`, `ui/dashboard-charts-logic.js::
   pickRunWithResults`) — «последним прогоном» для KPI-плиток и кольца
   «Статусы последнего прогона» теперь считается первый из ленты со
   статусом `passed`/`failed` и ≥ 20 результатами; `cancelled` остаётся в
   30-дневной динамике и в ленте прогонов, но не в этой роли. Подпись
   источника «по прогону #N · стенд · дата» (`#kpi-source`/
   `#status-donut-source`) ссылается на окно прогона. Бейдж «· N стенд» у
   «% passed» появляется, когда больше половины падений этого прогона
   классифицированы как инфраструктурные (`app/core/failure_causes.py`);
   для этого `GET /api/projects/{name}/runs` теперь отдаёт `stand_failures`
   на каждый прогон, не только внутри `delta_prev`.
2. **«Статистика» без полного прогона на стенде** (`ec929db`,
   `app/core/stats.py::_latest_full_run`/`_latest_run_on_stand`,
   `app/routers/stats.py`, `ui/stats.js`) — если на стенде нет ни одного
   прогона с `target = 'all'`, `GET /api/projects/{name}/stats` отдаёт
   `full_run: null` и `fallback_run` (id/цель/дата последнего прогона
   стенда); вместо таблицы разделов в нулях UI показывает состояние
   «Полного прогона на стенде «<имя>» не было» с кнопкой «Показать по
   последнему прогону» (считает ту же таблицу по частичному прогону, с
   пометкой «Частичный прогон, N из M тестов», без блока «Разделы без
   единого теста»).
3. **Сплит окна прогона по тем же финальным попыткам, что и счётчики**
   (`17b9a87`, `app/routers/runs.py::list_run_tests`) — список «Тесты»
   после завершения прогона строится через
   `allure_report.final_attempts(parse_results(...), row["repeat"])`, а не
   напрямую из `parse_results`: реран (pytest-rerunfailures) больше не
   плодит несколько строк на один тест (прогон #105 из факта миссии: было
   72 строки при 57 по счётчикам шапки, теперь суммы совпадают). Ответ
   несёт поле `attempts`; если тест в итоге `passed`, но `attempts > 1` —
   пометка «прошёл со 2-й попытки» / «с N-й попытки»
   (`ui/run-window-split-logic.js::attemptsBadgeText`,
   `ui/project-run-window.js`). Во время прогона — по-прежнему одна строка
   на nodeid со статусом последнего `test_end`.
4. **Флаки: `fails`/`flips` на одном и том же наборе результатов**
   (`17b9a87`, `app/core/flaky.py::recalc`) — до правки `fails` уже
   пропускал падения с инфраструктурной причиной (`cause != 'code'`), а
   `flips` считался по последовательности с наследованием эффективного
   статуса предыдущего элемента — инфраструктурное падение или `skipped`
   всё равно мог протащить флип через унаследованный статус, и тест с
   `fails = 0` показывал ненулевую нестабильность (факт миссии: 4
   запуска/0 падений/67 %). Теперь `flips` считается по той же урезанной
   последовательности, что и `fails`: инфраструктурные падения и `skipped`
   просто выбрасываются из последовательности, а не наследуются —
   `fails = 0` всегда даёт `flips = 0`. Колонка «Из них стенд»
   (`stand_fails`, миграция `flaky_stats.stand_fails` в `app/db.py`) в
   таблице «Флаки» (`ui/project-flaky.js`) показывает число исключённых
   инфраструктурных падений; подсказка у «% нестабильности» объясняет
   правило.
5. **Ретеншен результатов на диске** (`f5c54b7`, `ed97977`,
   `app/core/retention.py`, `app/main.py::lifespan`,
   `app/routers/admin.py`, `ui/admin_all.html`/`admin-logic.js`) — фоновая
   задача `retention_loop` раз в сутки (запускается/отменяется в
   `lifespan`, сам `purge_expired()` — через `asyncio.to_thread`, чтобы
   `shutil.rmtree` на гигабайтах видео не замораживал event loop) удаляет у
   завершённых прогонов каталоги видео/кадров/allure-results/allure-
   отчётов старше `TH_KEEP_VIDEO_DAYS` (14) / `TH_KEEP_FRAMES_DAYS` (30) /
   `TH_KEEP_RESULTS_DAYS` (90) / `TH_KEEP_REPORTS_DAYS` (30) дней; `0` в
   любой из переменных отключает удаление только своей категории. Строки
   `runs`/`counts`/`run_test_results`/`run_events` не трогаются. Прогон с
   живой share-ссылкой (не `revoked`, `expires_at` в будущем или `NULL`) не
   удаляется, пока ссылка жива. Суперадминка показывает строку «Диск: видео
   X ГБ, результаты Y ГБ, отчёты Z ГБ, кадры W ГБ» и кнопку «Очистить
   сейчас» (`POST /api/admin/retention/purge`, только `superadmin`). В окне
   прогона удалённые по сроку видео/кадры показывают «удалено по сроку
   хранения (N дней)» вместо «Плагин не записал видео» (`video_purged`/
   `frames_purged` в `GET /api/runs/{id}/tests`, `has_video`/`has_frames`
   остаются `true` навсегда).

## Изменённые файлы (по коммитам реализации)

`app/core/stats.py`, `app/core/flaky.py`, `app/core/retention.py` (новый),
`app/core/failure_causes.py` (не менялся, только читается), `app/db.py`
(миграция `flaky_stats.stand_fails`), `app/main.py` (запуск
`retention_loop` в `lifespan`), `app/routers/stats.py`,
`app/routers/runs.py`, `app/routers/admin.py`, `app/routers/flaky.py`,
`app/routers/schedules.py`, `app/schemas.py`, `app/config.py`
(`TH_KEEP_*_DAYS`), `.env.example`, `.gitignore` (`*.log`); `ui/stats.js`,
`ui/stats.html`, `ui/project-dashboard.js`, `ui/project-flaky.js`,
`ui/project-run-window.js`, `ui/run-window-split-logic.js`,
`ui/run-live-logic.js`, `ui/dashboard-charts-logic.js`, `ui/admin_all.html`,
`ui/admin_all.js`, `ui/admin-logic.js` (новый), `ui/project.html`,
`ui/style.css`.

## Результаты прогона тестов

Все команды выполнялись в этом worktree (`.venv` — общий symlink на
`test_hub/.venv`), в foreground.

**Тесты этой миссии** (`pytest -q`, по файлам, добавленным/изменённым
коммитами 1+2/3+4/5):

```
tests/test_stats.py tests/test_stats_api.py tests/test_run_list_stand_failures.py
tests/test_project_dashboard_source_badge_js.py tests/test_stats_sections_fallback_js.py
```
→ **54 passed**.

```
tests/test_flaky.py tests/test_run_tests_api.py tests/test_run_window_split_ui.py
tests/test_admin_logic_js.py
```
→ **48 passed, 2 warnings** (предупреждения — `StarletteDeprecationWarning`
про `httpx`/`anyio`, не относятся к коду миссии).

```
tests/test_retention.py tests/test_admin.py
```
→ **51 passed**.

**JS-логика этой миссии** (`node tests/js/<файл>.js`, по одному файлу —
foreground):
`test_project_dashboard_source_badge.js` (10/10),
`test_stats_sections_source_fallback.js` (8/8),
`test_run_window_split_logic.js` (12/12 — включая `attemptsBadgeText`),
`test_run_live_logic.js` (36/36 — включая `videoRetentionMessage`/
`framesRetentionMessage`), `test_admin_logic.js` (9/9 — `formatGb`/
`diskUsageLine`). Остальные 16 файлов в `tests/js/` (не относящиеся к этой
миссии) — тоже зелёные, суммарно без одного падения.

**Весь набор** (`pytest -q`, без выбора файлов, из корня репозитория) →
**1381 passed, 3 xfailed, 4 failed in 597.5 с**. Все 4 падения не связаны с
кодом этой миссии — известные хрупкие UI-smoke тесты на порядок кнопок-
пресетов «Запуска»/«Расписаний» и на пилюлю Pixel 7 в ленте/таблице
(`tests/test_sections_tree_ui_smoke.py`,
`tests/test_schedules_table_ui_smoke.py`, `tests/test_mobile_frame_ui.py`),
воспроизводимые и без изменений этой задачи — ни один файл из их тест-кейсов
README/отчёт не затрагивает.

## Открытые пункты

Авторы задач по пунктам 1+2, 3+4 и 5 (коммиты `ec929db`, `17b9a87`,
`f5c54b7`/`ed97977` и три коммита тестов `011b765`/`9338db3`, `62a05e5`,
`19f0bd3`) не оставили в сообщениях коммитов или коде пометок о найденном,
но не исправленном несоответствии критериям миссии — ни «дефект», ни
«TODO», ни эквивалентной формулировки по этим пяти пунктам не найдено.
Открытых дефектов по итогам этой миссии нет.

## Контракт плагина, CI и схема покрытия

Не тронуты. Плагин проекта тестов (`utils/test_hub_plugin.py`) живёт в
`auto_tests_vshgu`, а не в этом репозитории — ни один файл текущей задачи
на него не похож и не меняет протокол `[TH] start/step/end`,
`TH_URL`/`TH_RUN_ID`/`TH_RUN_TOKEN` или эндпоинты
`/api/runs/{id}/frames`/`/live`/`tests/{nodeid}/video`. В репозитории нет
каталога `.github/` или другого CI-конфига, который правки могли бы
затронуть. `app/core/coverage.py` и `app/core/product_map.py` (схема
покрытия) не менялись — `git diff 216f48c..HEAD` по ним пуст.
