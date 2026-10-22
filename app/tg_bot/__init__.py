"""Telegram-бот test_hub на inline-кнопках (aiogram 3).

Главный сценарий — кнопочный: /start или текст «Меню» открывает список проектов,
дальше выбор стенда → набора тестов (Smoke/API/UI/Все) → подтверждение → запуск,
и всё это редактирует одно и то же сообщение (edit_text), не плодя новые. Текстовые
команды (/projects, /run, /status, /report, /last) дублируют тот же функционал через
HTTP API test_hub — обе ветки используют один и тот же HubClient.

Стенд с manual_only=1 (боевой stage, см. app/db.py::VSHGU_MANUAL_ONLY_STAND) вместо
маркеров показывает пресеты (build_preset_keyboard) и требует ещё один шаг
подтверждения (build_manual_confirm_keyboard/_manual_confirm_text) перед
submit_run(confirm_manual=True) — как для пресета (cb_preset/cb_preset_confirm),
так и для дерева тестов (cb_tree_run/cb_tree_run_confirm), и то же самое даёт
команда /stage <проект> <пресет>. Сервисная учётка бота при этом всё равно не
может ничего запустить на таком стенде — submit_run блокирует её отдельно, см.
app/core/runner.py::ManualRunNotConfirmed.

Бот работает поверх REST API самого test_hub (app/routers/projects.py, app/routers/runs.py)
под сервисной учёткой settings.TH_TG_SERVICE_LOGIN (сидится в app/db.py::_seed_tg_bot_user),
используя фичи t1 — RunCreate.marker и projects.use_env_flag/--env (app/schemas.py,
app/core/runner.py): маркер, выбранный кнопкой/введённый в /run, передаётся в
RunCreate.marker как есть, раннер сам решает, добавлять ли `-m <marker>` и
`--env <stand>` к pytest (см. build_run_args ниже — зеркалит этот же формат для UI).

Разбор callback_data/команд и построение аргументов вынесены в чистые функции
(parse_callback, parse_run_command, build_run_args, format_*) без объектов aiogram —
их можно юнит-тестировать напрямую, без сети и без запуска бота.

Пакет разбит по слоям (бывший единый файл на 2227 строк):
- client.py     — HubClient, HTTP поверх REST API test_hub
- parsing.py    — разбор текстовых команд
- callbacks.py  — кодирование/разбор callback_data инлайн-кнопок
- tree.py       — плоское дерево тестов (discover() -> список узлов)
- formatting.py — форматирование ответов бота
- keyboards.py  — инлайн-клавиатуры
- handlers.py   — router, middleware, все cb_*/cmd_* хендлеры, запуск приложения

Этот файл — фасад: реэкспортирует всё публичное (и часть приватного, нужного
тестам/app.core.schedule) под старыми именами `app.tg_bot.<имя>`, чтобы код,
писавший `from app import tg_bot; tg_bot.XXX`, не заметил переезда.

ВАЖНО для тестов: `_watch_run` определён и вызывается ВНУТРИ handlers.py — её
вызовы (например, из cb_tree_run_confirm) резолвятся через globals() этого же
модуля, а не через `app.tg_bot`. Поэтому `monkeypatch.setattr(tg_bot, "_watch_run", ...)`
патчит только реэкспорт здесь и не повлияет на реальные вызовы — тестам нужно
патчить `tg_bot.handlers._watch_run` (`from app import tg_bot; monkeypatch.setattr(tg_bot.handlers, "_watch_run", ...)`)."""
from __future__ import annotations

from . import handlers  # носитель состояния router/_watch_run — см. docstring выше
from .callbacks import (
    _decode_token,
    _encode_token,
    _NONE_TOKEN,
    build_callback,
    parse_callback,
)
from .client import HubClient
from .formatting import (
    FLAKY_TOP_N,
    MARKER_BUTTONS,
    MARKER_LABELS,
    MAX_ERROR_TEXT_LEN,
    MAX_FAILED_LABEL_LEN,
    MAX_FAILED_LISTED,
    MAX_REASON_LEN,
    STATS_SECTIONS_LIMIT,
    STATUS_RU,
    XFAIL_TOP_N,
    _bad_tests,
    _confirm_text,
    _counts_line,
    _error_text,
    _manual_confirm_text,
    _marker_label,
    _short_reason,
    _short_test_label,
    _stand_label,
    batch_line,
    format_causes,
    format_compare,
    format_data_batch,
    format_data_batches,
    format_data_confirm,
    format_flaky,
    format_project_card,
    format_projects,
    format_report,
    format_runs_list,
    format_schedules,
    format_stats,
    format_status,
    format_xfail,
    run_button_label,
    run_line,
)
from .handlers import (
    ACCESS_DENIED_MESSAGE,
    LAST_USAGE,
    MENU_TEXT,
    POLL_INTERVAL_SECONDS,
    REPORT_USAGE,
    SCHEDULE_USAGE,
    STAGE_STAND_NAME,
    TELEGRAM_CAPTION_LIMIT,
    TREE_CACHE_TTL_SECONDS,
    AccessMiddleware,
    TgApplication,
    _edit_menu,
    _get_preset_or_notify,
    _is_allowed,
    _load_tree,
    _log_polling_failure,
    _project_use_env_flag,
    _render_tree,
    _reply_http_error,
    _restart_tests,
    _safe_edit,
    _send_report_png,
    _show_menu,
    _stand_manual_only,
    _submit_selected_tests,
    _tree_nav_state,
    _watch_batch,
    _watch_run,
    build_application,
    cb_confirm,
    cb_data,
    cb_data_batch,
    cb_data_confirm,
    cb_data_delete,
    cb_data_new,
    cb_data_refresh,
    cb_data_scenario,
    cb_data_stand,
    cb_launch,
    cb_run_causes,
    cb_run_cleanup,
    cb_run_compare,
    cb_runs,
    cb_schedules,
    cb_stats,
    cb_fail_open,
    cb_fail_restart_all,
    cb_fail_restart_one,
    cb_flaky,
    cb_marker,
    cb_menu,
    cb_preset,
    cb_preset_confirm,
    cb_project,
    cb_run_cancel,
    cb_run_report,
    cb_run_section_confirm,
    cb_run_share,
    cb_run_status,
    cb_run_trend,
    cb_sched_toggle,
    cb_stand,
    cb_tests,
    cb_tree_clear,
    cb_tree_open,
    cb_tree_page,
    cb_tree_refresh,
    cb_tree_run,
    cb_tree_run_confirm,
    cb_tree_select_file,
    cb_tree_up,
    cb_xfail,
    cb_xfail_check,
    cmd_flaky,
    cmd_last,
    cmd_projects,
    cmd_report,
    cmd_run,
    cmd_schedules,
    cmd_stage,
    cmd_stats,
    cmd_status,
    cmd_xfail,
    on_menu_text,
    on_start,
    router,
    start_application,
    stop_application,
)
from .keyboards import (
    MAX_FAILED_BUTTONS,
    TREE_PAGE_SIZE,
    _tree_item_label,
    build_back_keyboard,
    build_batch_keyboard,
    build_confirm_keyboard,
    build_data_confirm_keyboard,
    build_data_keyboard,
    build_data_stand_keyboard,
    build_fail_detail_keyboard,
    build_manual_confirm_keyboard,
    build_marker_keyboard,
    build_preset_keyboard,
    build_project_keyboard,
    build_projects_keyboard,
    build_report_keyboard,
    build_run_keyboard,
    build_runs_keyboard,
    build_scenarios_keyboard,
    build_schedules_keyboard,
    build_stands_keyboard,
    build_tree_keyboard,
    build_tree_text,
)
from .parsing import (
    FLAKY_USAGE,
    RUN_USAGE,
    STAGE_USAGE,
    STATS_USAGE,
    STATUS_USAGE,
    XFAIL_USAGE,
    parse_flaky_args,
    parse_optional_run_id,
    parse_project_name,
    parse_run_args,
    parse_run_command,
    parse_run_id,
    parse_stage_args,
    parse_stats_args,
    parse_xfail_args,
)
from .tree import (
    build_flat_tree,
    build_full_name_index,
    build_run_args,
    _breadcrumb,
    _collect_test_nodeids,
    _nodeid_to_full_name,
    _sorted_children,
    _strip_param_suffix,
)
