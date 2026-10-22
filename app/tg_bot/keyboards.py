"""Инлайн-клавиатуры бота — строятся из build_callback (app.tg_bot.callbacks),
переиспользуют _stand_label/_short_test_label (app.tg_bot.formatting) и
_breadcrumb/_sorted_children (app.tg_bot.tree) для подписей кнопок."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .callbacks import build_callback
from .formatting import (
    DATA_BATCHES_N,
    DATA_DELETABLE_STATUSES,
    MARKER_BUTTONS,
    RUNS_LIST_N,
    _short_test_label,
    _stand_label,
    data_status_label,
    run_button_label,
    scenario_title,
)
from .tree import _breadcrumb, _sorted_children

MAX_FAILED_BUTTONS = 10


TREE_PAGE_SIZE = 8


def build_projects_keyboard(projects: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for project in projects:
        builder.button(text=project["name"], callback_data=build_callback("project", project=project["name"]))
    builder.adjust(1)
    return builder.as_markup()


def build_project_keyboard(project: str) -> InlineKeyboardMarkup:
    """Карточка проекта (22.10.2026) — вместо списка стендов с двумя кнопками внизу:
    всё, что есть у проекта в вебе — запуск, прогоны, данные, флаки, дефекты,
    статистика, расписания."""
    builder = InlineKeyboardBuilder()
    builder.button(text="▶️ Запуск", callback_data=build_callback("launch", project=project))
    builder.button(text="📋 Прогоны", callback_data=build_callback("runs", project=project))
    builder.button(text="🧪 Данные", callback_data=build_callback("data", project=project))
    builder.button(text="🔁 Флаки", callback_data=build_callback("flaky", project=project))
    builder.button(text="🐞 Дефекты", callback_data=build_callback("xfail", project=project))
    builder.button(text="📊 Статистика", callback_data=build_callback("stats", project=project))
    builder.button(text="⏰ Расписания", callback_data=build_callback("schedules", project=project))
    builder.button(text="« К проектам", callback_data="menu")
    builder.adjust(2, 2, 2, 1, 1)
    return builder.as_markup()


def build_stands_keyboard(project: str, stands: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if stands:
        for stand in stands:
            label = f"🔒 {stand['name']} (только вручную)" if stand.get("manual_only") else stand["name"]
            builder.button(
                text=label, callback_data=build_callback("stand", project=project, stand=stand["name"])
            )
    else:
        builder.button(text="Без стенда", callback_data=build_callback("stand", project=project, stand=None))
    builder.button(text="« К проекту", callback_data=build_callback("project", project=project))
    builder.adjust(1)
    return builder.as_markup()


def build_runs_keyboard(project: str, runs: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for run in runs[:RUNS_LIST_N]:
        builder.button(text=run_button_label(run), callback_data=build_callback("run_status", run_id=str(run["id"])))
    builder.button(text="« К проекту", callback_data=build_callback("project", project=project))
    builder.adjust(1)
    return builder.as_markup()


def build_schedules_keyboard(project: str, items: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in items:
        mark = "✅" if item.get("enabled") else "▫️"
        builder.button(
            text=f"{mark} #{item['id']}",
            callback_data=build_callback("sched_toggle", project=project, id=str(item["id"])),
        )
    builder.button(text="« К проекту", callback_data=build_callback("project", project=project))
    builder.adjust(1)
    return builder.as_markup()


# ------------------------------------------------------------------ «Данные»
def build_data_keyboard(project: str, supported: bool, batches: list[dict], scenarios: list[dict] | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if supported:
        builder.row(
            InlineKeyboardButton(text="➕ Создать данные", callback_data=build_callback("data_new", project=project)),
            InlineKeyboardButton(text="🔄 Обновить", callback_data=build_callback("data_refresh", project=project)),
        )
        for batch in batches[:DATA_BATCHES_N]:
            text = f"#{batch['id']} {data_status_label(batch.get('status'))} · {scenario_title(batch.get('scenario') or '', scenarios)}"
            builder.row(InlineKeyboardButton(
                text=text[:60], callback_data=build_callback("data_batch", project=project, id=str(batch["id"]))
            ))
    builder.row(InlineKeyboardButton(text="« К проекту", callback_data=build_callback("project", project=project)))
    return builder.as_markup()


def build_scenarios_keyboard(project: str, scenarios: list[dict]) -> InlineKeyboardMarkup:
    """Сценарии генератора по одному в строке, в порядке категорий из generate.py
    --list (там они уже сгруппированы); категория — префиксом подписи."""
    builder = InlineKeyboardBuilder()
    for scenario in scenarios:
        title = scenario.get("title") or scenario["name"]
        category = scenario.get("category")
        text = f"{category} · {title}" if category else title
        builder.row(InlineKeyboardButton(
            text=text[:60], callback_data=build_callback("data_sc", project=project, scenario=scenario["name"])
        ))
    builder.row(InlineKeyboardButton(text="« К данным", callback_data=build_callback("data", project=project)))
    return builder.as_markup()


def build_data_stand_keyboard(project: str, scenario: str, stands: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if stands:
        for stand in stands:
            builder.button(
                text=stand["name"],
                callback_data=build_callback("data_st", project=project, scenario=scenario, stand=stand["name"]),
            )
    else:
        builder.button(
            text="Без стенда", callback_data=build_callback("data_st", project=project, scenario=scenario, stand=None)
        )
    builder.button(text="« К сценариям", callback_data=build_callback("data_new", project=project))
    builder.adjust(1)
    return builder.as_markup()


def build_data_confirm_keyboard(project: str, scenario: str, stand: str | None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Создать", callback_data=build_callback("data_confirm", project=project, scenario=scenario, stand=stand)
    )
    builder.button(text="Отмена", callback_data=build_callback("data", project=project))
    builder.adjust(2)
    return builder.as_markup()


def build_batch_keyboard(project: str, batch: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    batch_id = str(batch["id"])
    builder.button(text="🔄 Обновить", callback_data=build_callback("data_batch", project=project, id=batch_id))
    if batch.get("status") in DATA_DELETABLE_STATUSES and (batch.get("created_total") or 0) > 0:
        builder.button(text="🗑 Удалить данные", callback_data=build_callback("data_del", project=project, id=batch_id))
    builder.button(text="« К данным", callback_data=build_callback("data", project=project))
    builder.adjust(1)
    return builder.as_markup()


def build_back_keyboard(callback_data: str, label: str = "« Назад") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=label, callback_data=callback_data)
    return builder.as_markup()


def build_marker_keyboard(project: str, stand: str | None, markers: list[dict] | None = None) -> InlineKeyboardMarkup:
    """markers — реальные маркеры проекта (GET /api/projects/{name}/markers, из
    pytest.ini); без них (нет конфига/ошибка API) — прежние Smoke/API/UI."""
    builder = InlineKeyboardBuilder()
    items = [(m["name"], m["name"]) for m in markers] if markers else [(l, m) for l, m in MARKER_BUTTONS if m]
    for label, marker in items:
        builder.button(text=label, callback_data=build_callback("marker", project=project, stand=stand, marker=marker))
    builder.button(text="Все", callback_data=build_callback("marker", project=project, stand=stand, marker=None))
    builder.button(text="Выбрать тесты", callback_data=build_callback("tests", project=project, stand=stand))
    builder.button(text="« К стендам", callback_data=build_callback("launch", project=project))
    total = len(items) + 1
    builder.adjust(*([2] * (total // 2) + ([1] if total % 2 else [])), 1, 1)
    return builder.as_markup()


def build_confirm_keyboard(project: str, stand: str | None, marker: str | None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Да", callback_data=build_callback("confirm", project=project, stand=stand, marker=marker))
    builder.button(text="Отмена", callback_data="menu")
    builder.adjust(2)
    return builder.as_markup()


def build_preset_keyboard(project: str, stand: str | None, presets: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for preset in presets:
        builder.button(
            text=preset["name"],
            callback_data=build_callback("preset", project=project, stand=stand, id=str(preset["id"])),
        )
    builder.button(text="Выбрать тесты", callback_data=build_callback("tests", project=project, stand=stand))
    builder.button(text="« К стендам", callback_data=build_callback("launch", project=project))
    builder.adjust(1)
    return builder.as_markup()


def build_manual_confirm_keyboard(yes_callback: str, cancel_callback: str = "menu") -> InlineKeyboardMarkup:
    """Подтверждение запуска на manual_only-стенде — тот же двухкнопочный вид,
    что и build_confirm_keyboard, но с явной формулировкой ("Да, запустить") и
    свободным yes_callback: вызывающий код (пресет/дерево) сам решает, что
    произойдёт по "Да" — submit_run с confirm_manual=True в разных вариантах
    target/marker, которые не укладываются в формат build_callback("confirm", ...)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, запустить", callback_data=yes_callback)
    builder.button(text="Отмена", callback_data=cancel_callback)
    builder.adjust(2)
    return builder.as_markup()


def build_run_keyboard(run_id: int, project: str | None = None) -> InlineKeyboardMarkup:
    """project — для кнопки «К проекту» (из отчёта прогона); там, где проект
    неизвестен (клавиатура после запуска), её нет."""
    builder = InlineKeyboardBuilder()
    rid = str(run_id)
    builder.button(text="Статус", callback_data=build_callback("run_status", run_id=rid))
    builder.button(text="Отчёт", callback_data=build_callback("run_report", run_id=rid))
    builder.button(text="Причины", callback_data=build_callback("run_causes", run_id=rid))
    builder.button(text="Сравнить", callback_data=build_callback("run_compare", run_id=rid))
    builder.button(text="Тренд", callback_data=build_callback("run_trend", run_id=rid))
    builder.button(text="Поделиться", callback_data=build_callback("run_share", run_id=rid))
    builder.button(text="🗑 Удалить данные прогона", callback_data=build_callback("run_cleanup", run_id=rid))
    builder.button(text="Отменить", callback_data=build_callback("run_cancel", run_id=rid))
    sizes = [2, 2, 2, 1, 1]
    if project:
        builder.button(text="« К проекту", callback_data=build_callback("project", project=project))
        sizes.append(1)
    builder.adjust(*sizes)
    return builder.as_markup()


def build_report_keyboard(run_id: int, failed: list[dict]) -> InlineKeyboardMarkup:
    """Обычная клавиатура прогона (build_run_keyboard) + до MAX_FAILED_BUTTONS кнопок
    упавших/сломанных тестов. Индекс кнопки — позиция в этом же списке `failed`,
    закэшированном per run_id (см. failed_cache) — сам callback_data хранит только
    run_id и индекс, не имя теста, поэтому укладывается в лимит Telegram (64 байта)
    независимо от длины nodeid/fullName (тот же приём, что и в дереве тестов)."""
    builder = InlineKeyboardBuilder(markup=build_run_keyboard(run_id).inline_keyboard)
    for index, test in enumerate(failed[:MAX_FAILED_BUTTONS]):
        builder.row(
            InlineKeyboardButton(
                text=f"❌ {_short_test_label(test.get('name') or '')}",
                callback_data=build_callback("fail_open", run_id=str(run_id), index=str(index)),
            )
        )
    return builder.as_markup()


def build_fail_detail_keyboard(run_id: int, index: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Перезапустить этот тест",
        callback_data=build_callback("fail_restart_one", run_id=str(run_id), index=str(index)),
    )
    builder.button(text="Перезапустить все упавшие", callback_data=build_callback("fail_restart_all", run_id=str(run_id)))
    builder.adjust(1)
    return builder.as_markup()


def _tree_item_label(node: dict, selected: set[str]) -> str:
    if node["kind"] == "test":
        mark = "✅" if node["nodeid"] in selected else "▫️"
        return f"{mark} {node['label']}"
    icon = {"dir": "📁", "file": "📄", "class": "🗂"}[node["kind"]]
    return f"{icon} {node['label']}"


def build_tree_text(nodes: list[dict], project: str, stand: str | None, node: int, selected: set[str], error: str | None) -> str:
    lines = [f"Проект: {project}", f"Стенд: {_stand_label(stand)}"]
    if error:
        lines.append(f"⚠️ {error}")
    lines.append(f"Путь: {_breadcrumb(nodes, node)}")
    lines.append(f"Выбрано тестов: {len(selected)}")
    lines.append("Выберите папку, файл или тест:" if nodes[node]["children"] else "Здесь пусто.")
    return "\n".join(lines)


def build_tree_keyboard(
    nodes: list[dict], project: str, stand: str | None, node: int, page: int, selected: set[str]
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    children = _sorted_children(nodes, node)
    start = page * TREE_PAGE_SIZE
    page_items = children[start : start + TREE_PAGE_SIZE]
    for child_idx in page_items:
        child = nodes[child_idx]
        builder.row(
            InlineKeyboardButton(
                text=_tree_item_label(child, selected),
                callback_data=build_callback("tree_open", node=str(child_idx)),
            )
        )

    nav_row = []
    if start > 0:
        nav_row.append(InlineKeyboardButton(text="‹ назад", callback_data=build_callback("tree_page", page=str(page - 1))))
    if start + TREE_PAGE_SIZE < len(children):
        nav_row.append(InlineKeyboardButton(text="вперёд ›", callback_data=build_callback("tree_page", page=str(page + 1))))
    if nav_row:
        builder.row(*nav_row)

    top_row = []
    if nodes[node]["parent"] is not None:
        top_row.append(InlineKeyboardButton(text="⬆ уровень выше", callback_data="tree_up"))
    top_row.append(InlineKeyboardButton(text="Обновить дерево", callback_data="tree_refresh"))
    builder.row(*top_row)

    if nodes[node]["kind"] == "file":
        builder.row(InlineKeyboardButton(text="Выбрать все в файле", callback_data="tree_select_file"))

    builder.row(
        InlineKeyboardButton(text="Сбросить", callback_data="tree_clear"),
        InlineKeyboardButton(text=f"Запустить выбранные ({len(selected)})", callback_data="tree_run"),
    )
    builder.row(InlineKeyboardButton(text="« К набору", callback_data=build_callback("stand", project=project, stand=stand)))
    return builder.as_markup()
