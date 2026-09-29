# QA-заметки: записка о хранении + макет вкладки «Тест-кейсы»

Проверка по чек-листу `docs/missions/2026-09-29_testcases_tab.md` (этап 1). Правки `app/`/`ui/`
не делались — только чтение и сверка с кодом test_hub и `auto_tests_vshgu_cloude`.

## 1. storage_options.md — без замечаний

- Ровно 3 варианта (А/Б/В), у каждого закрыты все 6 обязательных пунктов (источник истины,
  поток данных, правка, версионирование, переименование автотеста, объём работы) + рекомендация
  (Б → синк в Test IT вторым шагом) + список вопросов владельцу.
- Все технические ссылки на код сверены и актуальны на момент проверки:
  `app/core/sections.py` (`discover`/`mtime_signature`/кэш в `sections.json`),
  `app/db.py:44-57` (`runs.counts`), `app/core/xfail_registry.py:243-256`
  (`_nodeid_to_full_name`), `app/core/xfail_registry.py::recalc` (upsert `issue_url`/`note` не
  затирается), `app/routers/xfail.py` (`PUT /{name}/xfail/{entry_id}`, роль `qa` через
  `require_roles("qa")`), `app/core/runner.py:271` (`xfail_registry.recalc` вызывается из
  `_finalize`) — всё совпадает 1:1.
- Ссылки на `auto_tests_vshgu_cloude` (`tools/test_cases/generate.py`,
  `tools/test_cases/testit_sync.py`, `tools/test_cases/achievements_cases.py`,
  `.env.example:93-96`) проверены по актуальному коду — расхождений нет.

## 2. mockups.html + JPG

### Найден дефект — обрезан верх во всех 4 JPG

Во всех четырёх экспортированных JPG (`testcases-tree-dark.jpg`, `testcases-tree-light.jpg`,
`testcases-table-dark.jpg`, `testcases-table-light.jpg`) верх кадра обрезан: не видно ни
названия макета и переключателя вариантов («test_hub · вкладка «Тест-кейсы»…», кнопки
«1 · Дерево + карточка» / «2 · Таблица»), ни заголовка `h2` конкретного варианта («Вариант 1 ·
Дерево разделов + карточка кейса» / «Вариант 2 · Таблица с раскрывающимися шагами»), ни первой
строки его описания. Первое, что видно на JPG сверху — блок «Цвет проекта / Тема» и сразу под
ним вторая-третья строка описания варианта, только потом рамка макета.

В `mockups.html` все эти элементы на месте (строки 139–147 `.ctl`, 150–164/166–196 `.mock-head`
с `<h2>`), проблема именно в экспорте: `.ctl` — `position:sticky; top:0; z-index:20`
(`mockups.html:33`), и при скролле/захвате конкретного варианта он перекрывает верх секции.
Смотрится как недостаточный `scroll-margin-top`/`clip` в скрипте экспорта JPG (Playwright) —
кадр не поднят выше перекрывающей sticky-панели. Из самого JPG нельзя понять, какой это вариант
и какая тема, если не сверяться с текстом ниже или с именем файла.

Проверено через `PIL.Image.crop` по всем 4 файлам — дефект идентичен на всех.

### Остальное по чек-листу — без замечаний

- Оба варианта присутствуют (`#v1` — дерево + карточка, `#v2` — таблица с аккордеоном) и
  переключаются кнопками `.tabs`; обе темы (`data-theme="light"`/тёмная по умолчанию)
  переключаются кнопкой `#theme`, вёрстка не ломается ни в одной комбинации — 4 JPG
  просмотрены визуально, сетки/таблицы/дерево не разъезжаются.
- Данные — 29 кейсов из 4 разделов (tickets/notifications/learning_statistics/knowledge_base,
  `mockups.html:208-452`), что укладывается в требуемые 20–30 из 3–4 разделов
  (`grep -c '{id:' mockups.html` → 29).
- Названия/шаги/приоритеты/nodeid сверены построчно с реальными источниками — совпадают
  дословно: `docs/test_cases/tickets.md` (TC-TICKETS-001…012), `docs/test_cases/notifications.md`
  (TC-NOTIFICATIONS-001…024), `docs/test_cases/learning_statistics.md`,
  `docs/test_cases/knowledge_base.md` — все в `auto_tests_vshgu_cloude`; 3 кейса без автотеста
  («статья», «курс», «История достижений пользователя») дословно совпадают с
  `tools/test_cases/achievements_cases.py` (`material_case("article")`, `COURSE_CASE`,
  `HISTORY_CASE`). Подмены/выдумки не найдено.
- Токены — строго из `DESIGN.md`: цвета, шрифты (Golos Text/JetBrains Mono), радиусы, отступы,
  тени `elevation.card`/`cardLight` — построчно совпадают с `:root`/`:root[data-theme="light"]`
  в `mockups.html:9-24`. Структура шапки проекта и вкладок (`Дашборд/Запуск/Расписания/
  История/Флаки/Тест-кейсы`) совпадает с реальным `ui/project.html:26-30`.
- Ровно 4 JPG, все реально 1440 px шириной (`file`: 1440×2240 для табличного варианта,
  1440×2027 для дерева, обе темы).
- Текстов вида «скоро»/TODO/лорем ипсум не найдено (`grep -i` по mockups.html — пусто).

## 3. Ограничение «только docs/»

`git diff --stat` между веткой и `main` по коммитам `84022da` (записка) и `545835c`/`ea9b7b0`
(макет+JPG) показывает изменения только в `docs/missions/testcases/**`. Код `app/`/`ui/` не
менялся.
