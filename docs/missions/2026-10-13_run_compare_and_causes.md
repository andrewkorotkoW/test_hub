# Миссия: окно прогона — «Сравнить с…» и «Причины падений» (волны 429/401/5xx)

Записано 13.10.2026 по решению владельца: test_hub — основной раннер (ручные и выборочные прогоны,
история, флаки, Telegram), CI — только гейт. Разбор ночного прогона develop (#65 против #64) и
k8s-прогона в 4 потока (#66: две волны 429 от одной реплики) пришлось собирать руками из
`run_events`/allure — это должен делать сам test_hub. Кликабельный макет обеих вкладок на реальных
данных — `docs/missions/redesign/run_compare/mockups.html` (тёмная/светлая тема, токены DESIGN.md);
делать по нему, не выдумывать другую раскладку.

## Где это живёт сейчас

- Итоги прогона: `runs.counts` (JSON passed/failed/broken/skipped…) пишет `app/core/runner.py::_finalize`,
  там же после завершения запускаются `flaky.recalc` и прочие пост-обработчики (в `asyncio.to_thread`).
- Тесты прогона со статусами/длительностью/сообщением: `app/core/allure_report.py::parse_results`
  (`name` = allure fullName, `status`, `duration`, `message`, `trace`), приведение fullName → pytest nodeid —
  `app/routers/runs.py::list_run_tests` через `_full_name_index(runner.discover(...))`.
- Время каждого теста внутри прогона: `run_events` (`kind` = test_start/test_end, `ts`, `nodeid`);
  под xdist статусы есть только в строках `[gwN] [ xx%] STATUS nodeid` (`kind='line'`) —
  `runner.end_status_from_line`.
- Окно прогона: `ui/project.html` `#run-card` → `#run-view-toggle` (кнопки `data-view=split|log`),
  `ui/project-run-split.js`, `ui/project-run-window.js`; таблица «История» — `#history-rows` (`ui/project.js`).
- Telegram: `app/tg_bot/formatting.py::format_report` (`_counts_line`, `_bad_tests`, `_short_reason`),
  шлёт `app/core/schedule.py::_notification_caption`.
- Флаки: `app/core/flaky.py::recalc` считает `fails`/`flips` по allure-статусам последних прогонов.

## Что сделать

### 1. Классификатор причин падения (бэкенд, чистая функция)

`app/core/failure_causes.py::classify(message: str | None, trace: str | None) -> str`, значения:

| cause        | правило (по `statusDetails.message`/`trace` из allure)                                         | тип   |
|--------------|-------------------------------------------------------------------------------------------------|-------|
| `throttling` | `429`, `Too Many Requests`, `X-RateLimit`, а также `LoginError … не заданы K8S_LOGIN` (сессия не поднялась из-за 429 — см. memory k8s) | стенд |
| `session`    | `401`, `Unauthenticated`, `Unauthorized`, редирект на `/auth/main` после логина                   | стенд |
| `stand`      | `5xx`, `ReadTimeout`, `ConnectTimeout`, `RemoteDisconnected`, `Connection reset`, `ECONNREFUSED`, `Gateway`, `Timeout 30000ms exceeded` при `goto`/`expect_response`, 180 с таймаут LLM (`ai_chat`) | стенд |
| `code`       | всё остальное: `AssertionError`, `TimeoutError` на локаторе, `KeyError`, `JSONDecodeError` без 5xx | тест или продукт |

Первое совпадение по приоритету сверху вниз. Паттерны — в одном словаре `PATTERNS: dict[str, tuple[re.Pattern, ...]]`,
чтобы их было легко расширять. На вход ещё `nodeid`, чтобы `tests/ui/ai_chat/**` с таймаутом классифицировать как `stand`
(LLM стенда), а не `code`.

Результат сохраняется в новую таблицу `run_test_results (run_id, nodeid, full_name, status, duration, cause, finished_ts)`
(PK run_id+nodeid; `finished_ts` — из `run_events` test_end/`[gwN]`-строки, иначе NULL) — заполняется в
`_finalize` в том же `to_thread`-блоке, что `flaky.recalc`. Для старых прогонов — ленивый пересчёт при первом
запросе сравнения/причин (allure-results на диске есть). Миграция — как `_migrate_add_column`.

### 2. Волны

`failure_causes.detect_waves(results) -> list[{cause, start_ts, end_ts, count}]`: окно скользящее, волна — ≥5 падений
одной инфраструктурной причины (`throttling`/`session`/`stand`) за ≤2 минуты, соседние окна склеиваются. Пример
для проверки — #66: волны 09:43–09:50 (70 × 429) и 10:44–10:47 (15 × 429).

### 3. API

- `GET /api/runs/{id}/causes` → `{summary: {throttling, session, stand, code, total}, waves: [...], tests: [{nodeid,
  full_name, status, cause, finished_ts, duration, short_reason}]}`. `short_reason` — как `_short_reason` в tg_bot
  (вынести в общий модуль).
- `GET /api/runs/{id}/compare?base={base_id}` → `{base: {id, …}, kpis: {passed, failed, skipped, duration: {now, was}},
  groups: {new_failures: [...], fixed: [...], still_failing: [...], speed: [...]}}`. Сравниваются **финальные** статусы
  (после реранов); `failed`+`broken` — одно ведро (как `stats._bucket_status`), xfail/xpass — отдельно
  (`xfail → xpass` попадает в `fixed`). `speed` — статус не менялся, длительность отличается больше чем вдвое и
  ≥5 с. Без `base` — предыдущий завершённый прогон того же проекта/стенда с тем же `target` и `marker`
  (`stats.latest_finished_run_id` + фильтр), если нет — последний на том же стенде.
- В `GET /api/projects/{name}/runs` — поле `delta_prev: {passed, failed, stand_failures}` относительно предыдущего
  прогона на том же стенде (для столбца в «Истории»).

### 4. UI — две новые вкладки в окне прогона

В `#run-view-toggle` добавить `data-view=compare` («Сравнить с…») и `data-view=causes` («Причины N», N = число
падений). Доступны только для завершённых прогонов. Раскладка — строго по макету:

- **Сравнить с…**: селект базы (предыдущий по умолчанию, список последних 10 на стенде), 4 KPI «стало / было»
  с дельтой; четыре группы на `<details>` — «Новые падения» и «Починилось» раскрыты, «Падало и падает» и
  «Стали быстрее / медленнее» свёрнуты; строка теста = точка статуса, `nodeid` (путь — в `<small>`), тег
  причины (`стенд` голубой `--stand`, `тест/продукт` `--failed`, `passed`/`xfail → xpass` зелёный, известное —
  серый), длительность «теперь ← было» с подсветкой. Клик по строке открывает тест в сплите.
- **Причины**: светофор из 5 кнопок (всего / троттлинг / сессия / не ответил / тест или продукт) — фильтр списка;
  таймлайн прогона (SVG: падения в минуту столбиками цветом причины, passed — точки, волны — пунктирные
  рамки с подписью «hh:mm–hh:mm · N × 429»); под ним — заметка-вердикт («стенд, не код» если ≥90 % падений
  инфраструктурные); карточка «Уведомление в Telegram» с текстом сводки; список падений с тегом причины и
  временем.
- В «Истории» — столбец «Δ к предыдущему»: `+7 +31 · 36 стенд` (зелёный/красный/серый, моноширинный).
- Чистая логика (группировка сравнения, фильтр причин, разбиение на минуты для таймлайна) — в
  `ui/run-compare-logic.js` без DOM, node v12 (без `??`/`?.`), юнит-тесты в `tests/js/`.

### 5. Telegram и флаки

- `format_report`: после строки счётчиков — строка причин, если есть инфраструктурные падения:
  «Из 96 падений 94 — стенд: 70 × троттлинг 429 (две волны, 09:43–09:50 и 10:44–10:47), 10 × потеря сессии,
  14 × таймаут/не ответил. Тест или продукт — 2: …» и список «Упавшие тесты» ограничить **только** `code`-падениями
  (стендовые не перечислять — их и так видно в сумме). Плюс строка «Сравнение с #64: passed −54, новых падений 87».
- `flaky.recalc`: падения с `cause != code` не считать за `fails`/`flips` (брать статус из `run_test_results`, при его
  отсутствии — как сейчас). Иначе одна волна 429 делает флаки половину проекта.

### 6. Тесты и документация

- `tests/test_failure_causes.py`: классификатор на реальных сообщениях (взять из allure #65/#66 — 429, 401,
  ReadTimeout, LoginError K8S_LOGIN, AssertionError, ai_chat 180 с), `detect_waves` на синтетическом ряду и на
  #66-подобном; `tests/test_run_compare_api.py`: группы, выбор базы по умолчанию, xfail → xpass в fixed, `speed`;
  `tests/test_run_causes_api.py`; расширить `tests/test_tg_bot*.py` на новую строку и ограничение списка;
  `tests/test_flaky.py` — стендовые падения не считаются; smoke UI (`tests/test_project_tabs_ui.py` и соседние)
  на две новые кнопки и столбец Δ; JS-тесты логики.
- README: раздел «Причины падений и сравнение прогонов» (таблица правил классификатора, что считается
  волной, как читать Δ в истории, что во «Флаки» не идут стендовые падения).

## Правила

- Ветка от `main`, `pytest -q` зелёный (известный флак `test_runner_timeout.py` не считать), JS-тесты зелёные.
- Контракты `/live`, `/video`, `/frames`, сплит и схему покрытия не трогать; `runs.counts` и существующие поля
  ответов API не менять — только добавлять.
- Классификатор не должен ронять `_finalize`: любая ошибка парсинга → `cause='code'` и запись в лог.
- Скриншоты обеих вкладок (светлая/тёмная) в отчёт — `docs/reports/2026-10-13_run_compare_and_causes.md`.
- Без трейлера Co-Authored-By в коммитах.
