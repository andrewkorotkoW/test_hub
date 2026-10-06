# Миссия: параллельный запуск по стенду — поле `stands.workers` → `pytest -n <workers>`

Записано 06.10.2026 по решению владельца: «4 потока по умолчанию для стенда k8s» (троттлинг API на
релизном k8s v2 снят девопсом 06.10, прогон 300 тестов в 4 потока — 27 мин вместо 1 ч 34 мин; см.
qa_analysis/cases/K8S_v2_2026-10-06/report.md). Проект автотестов уже содержит pytest-xdist.

## Что сделать

1. Колонка `stands.workers INTEGER NOT NULL DEFAULT 0` (миграция `_migrate_add_column`, как `runs.mobile`).
   0 — без `-n` (как сейчас, последовательно). Поля `workers: Optional[int]` в `StandCreate`/`StandUpdate`
   (`app/schemas.py:43`), валидация 0..16, обработка в `create_stand`/`update_stand` (`app/routers/projects.py`),
   `workers` в `_stands_for` и ответах API стендов.
2. Раннер (`app/core/runner.py::_execute`, сборка `args` после `--env`/`-m`): если у стенда `workers > 0`,
   добавить `["-n", str(workers)]`. Для прогонов с `live=true` (эфир) и `repeat > 1` (флаки-детектор) — **не**
   добавлять `-n` (эфир с несколькими воркерами перемешивает кадры; repeat гоняет одну цель). Записать это
   в докстринг.
3. UI формы стенда (страница проекта/настройки стендов, где редактируются url/login/sentry): числовое поле
   «Потоки (pytest -n)», 0 = последовательно, подсказка «на k8s v2 троттлинг снят, 4 потока — 27 мин вместо
   1,5 ч». В списке стендов — пометка «×4» рядом с именем, если workers > 0.
4. Тесты: по образцу `tests/test_run_live_flag.py` — стенд с workers=4 даёт `-n 4` в args; workers=0 — нет
   `-n`; live=true или repeat>1 — нет `-n` даже при workers=4; миграция на старой БД; API create/update
   принимает и возвращает workers; smoke страницы на наличие поля.
5. README: абзац про поле и ограничения. После слияния владелец (или дежурный) выставляет k8s → 4.

## Правила

- Ветка от `main`, `pytest -q` зелёный (известный флак `test_runner_timeout.py` не считать), контракт
  `/live`, `/video`, схему покрытия не трогать. Отчёт — `docs/reports/2026-10-06_stand_workers.md`.
