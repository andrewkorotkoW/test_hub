# Миссия: вкладка «Тест-кейсы» — этап 2, реализация

Записано 29.09.2026. Решения владельца (все приняты):
- хранение — **вариант Б**: таблица `test_cases` в `workspace/test_hub.db`, test_hub —
  источник истины (`docs/missions/testcases/storage_options.md`, `report.md` разд. 2 и 5);
- права как у `xfail_registry`: `qa` правит, `manager`/`customer` читают;
- первый источник — импорт markdown-черновиков `docs/test_cases/*.md` из проекта
  `/Users/andreykorotkow/PycharmProjects/auto_tests_vshgu` (парсер по образцу
  `tools/test_cases/testit_sync.py::parse_area_file` портировать в test_hub); кейсы и с
  автотестом, и без (ручное заведение в UI);
- **макет: оба варианта** — вид «дерево разделов + карточка кейса» (по умолчанию) и вид
  «таблица с раскрывающимися шагами», переключатель вида в шапке вкладки
  (`docs/missions/testcases/mockups.html`, JPG `testcases-tree-*`, `testcases-table-*`);
- **в кейсах должны быть скриншоты**: у шага — одна или несколько картинок;
- Test IT не трогать: синка нет и не планируется.

## Что должно получиться

1. **БД**: `test_cases(id, project, section, title, steps JSON [{n, action, expected,
   attachments:[...]}], precondition, priority, nodeid NULL, source generated|manual,
   updated_at, updated_by)`; `test_case_attachments(id, case_id, step_n, path, source
   allure|manual, created_at)`. Файлы — `workspace/testcases/<project>/<case_id>/…`,
   в БД только пути. Миграции через `_migrate_add_column`/CREATE IF NOT EXISTS.
2. **Импорт**: `POST /api/projects/{name}/testcases/import` (роль qa) читает
   `docs/test_cases/*.md` из пути проекта, upsert по `(project, nodeid)`; кейсы с
   `source=manual` не затираются. Ручное создание `POST /api/projects/{name}/testcases`.
3. **Чтение**: `GET /api/projects/{name}/testcases` — дерево по разделам (реюз
   `sections.py`), у кейса с nodeid — статус последнего прогона (nodeid → fullName →
   `allure_report.parse_results`, как в `xfail_registry`), фильтры: раздел, статус,
   есть/нет автотест; поиск по названию и шагам. `GET .../testcases/{id}` — карточка.
4. **Правка**: `PUT .../testcases/{id}` (qa) — название, предусловие, приоритет, шаги,
   nodeid; `source → manual`.
5. **Скриншоты**: (а) автоматически — после каждого прогона (`runner.py::_finalize`, рядом с
   `xfail.recalc`) для кейсов с nodeid берём image-вложения allure этого теста (по шагам, если
   attachment внутри step, иначе к кейсу целиком) и копируем в хранилище кейса как
   `source=allure`, заменяя предыдущие allure-снимки; (б) вручную — `POST
   .../testcases/{id}/steps/{n}/attachments` (qa, multipart PNG/JPG, лимит размера),
   `DELETE` для ручных. В карточке — миниатюры у шага, клик — просмотр в модалке.
6. **UI**: вкладка «Тест-кейсы» в `ui/project.html` (`data-tab-panel="testcases"`, `#testcases`),
   оба вида по макету, переключатель вида хранится в localStorage; карточка кейса с шагами и
   скриншотами, кнопки «Импортировать черновики», «Новый кейс», «Правка» — только для qa.
   Токены из `DESIGN.md`, обе темы, цвет проекта.

## Ограничения

- Существующие тесты проходят; новые: миграции, импорт (фикстурный md), права ролей,
  GET/PUT, вложения (лимит, удаление), копирование allure-снимков на фикстурных
  allure-results, UI-логика без браузера.
- Стенды VSHGU не трогать, прогоны не запускать. Коммиты небольшие, на русском.
- Скриншоты `docs/screenshots/testcases_*.png` (оба вида, обе темы).

## Приёмка

Импорт черновиков VSHGU → дерево разделов с кейсами и статусами последнего прогона;
переключение видов; правка кейса под qa, под manager только чтение; у кейса с автотестом
после прогона появились скриншоты шагов; ручная загрузка и удаление картинки работают.
