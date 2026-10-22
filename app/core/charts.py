"""PNG-рендер отчёта прогона и тренда на matplotlib (backend Agg).

Чистые функции над структурами из app.core.allure_report / app.routers.runs::get_report
(run-payload с counts/tests, список тестов name/status/duration/message) — без записи
на диск, без сети и без обращений к БД: только bytes на выходе.

С 22.10.2026 — светлая тема в стиле окна прогона (ui/style.css, тема light:
--bg #f5f6f8, --surface #ffffff, --text #1f2430, --accent #2563eb, статус-цвета
--passed/--failed/--broken/--skipped) вместо старого тёмно-неонового макета: бот
показывает ту же картинку, что и веб. Содержимое повторяет верх окна прогона:
шапка (проект, статус, стенд/маркер, период, длительность «23 мин 2 с», pass rate,
причины падений), кольцо итога, тренд по стенду с подписями «#96 · 19.10», топ-10
самых долгих тестов по финальной попытке с подписями «4:37»/«53.5 с».
"""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  (после matplotlib.use)
from matplotlib.patches import FancyBboxPatch  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

from . import allure_report  # noqa: E402
from .fmt import fmt_dt, fmt_run_duration, fmt_test_duration, pass_rate, short_test_name  # noqa: E402

STATUSES = ("passed", "failed", "broken", "skipped")

PAGE = "#f5f6f8"
SURFACE = "#ffffff"
INK_PRIMARY = "#1f2430"
INK_SECONDARY = "#4b5563"
INK_MUTED = "#6b7280"
GRIDLINE = "#e1e4e9"
BASELINE = "#d1d5db"
ACCENT = "#2563eb"

STATUS_COLORS = {
    "passed": "#16a34a",
    "failed": "#dc2626",
    "broken": "#d97706",
    "skipped": "#6b7280",
}

RUN_STATUS_RU = {
    "queued": "в очереди",
    "running": "выполняется",
    "passed": "пройден",
    "failed": "провален",
    "cancelled": "отменён",
}

RUN_STATUS_COLORS = {
    "passed": STATUS_COLORS["passed"],
    "failed": STATUS_COLORS["failed"],
    "cancelled": INK_MUTED,
    "running": ACCENT,
    "queued": INK_MUTED,
}

CAUSE_LABELS = {
    "throttling": "429",
    "session": "сессия",
    "stand": "стенд",
    "code": "код",
}

FONT_FAMILY = ["Golos Text", "system-ui", "Segoe UI", "DejaVu Sans", "sans-serif"]

TOP_N = 10
TREND_LIMIT = 10
TREND_PNG_LIMIT = 30


def _apply_rc() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": FONT_FAMILY,
            "text.color": INK_PRIMARY,
            "axes.edgecolor": BASELINE,
        }
    )


def _new_figure(width_px: int, height_px: int, dpi: int = 100) -> plt.Figure:
    fig = plt.figure(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
    fig.patch.set_facecolor(PAGE)
    return fig


def _fig_to_png_bytes(fig: plt.Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


def _card(fig: plt.Figure, rect: tuple[float, float, float, float]) -> None:
    """Белая «карточка» со скруглением и рамкой — как .card в вебе. rect = (x0, y0, w, h)
    в долях фигуры. zorder < 0: fig.patches рисуются после осей, при zorder 0 карточка
    закрыла бы содержимое."""
    x0, y0, w, h = rect
    patch = FancyBboxPatch(
        (x0, y0), w, h,
        boxstyle="round,pad=0,rounding_size=0.012", transform=fig.transFigure,
        facecolor=SURFACE, edgecolor=GRIDLINE, linewidth=1, zorder=-1,
    )
    fig.patches.append(patch)


def _card_axes(fig: plt.Figure, card: tuple[float, float, float, float],
               inset: tuple[float, float, float, float]):
    """Карточка и ось внутри неё: inset = (слева, снизу, справа, сверху) — отступы в
    долях фигуры под заголовок/подписи тиков, чтобы они не вылезали за карточку."""
    _card(fig, card)
    x0, y0, w, h = card
    left, bottom, right, top = inset
    ax = fig.add_axes((x0 + left, y0 + bottom, w - left - right, h - bottom - top))
    ax.set_zorder(1)
    return ax


def _blank_axes(ax) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def _placeholder(ax, text: str = "нет данных") -> None:
    _blank_axes(ax)
    ax.text(0.5, 0.5, text, ha="center", va="center", color=INK_MUTED, fontsize=12)


def _title(ax, text: str) -> None:
    ax.set_title(text, loc="left", fontsize=12, color=INK_PRIMARY, fontweight="bold", pad=12)


def _module_of(name: str) -> str:
    if not name:
        return "unknown"
    if "::" in name:
        return name.split("::", 1)[0]
    if "#" in name:
        return name.split("#", 1)[0]
    if "." in name:
        return name.rsplit(".", 1)[0]
    return name


def _truncate(name: str, limit: int = 46) -> str:
    if not name:
        return "—"
    return name if len(name) <= limit else "…" + name[-(limit - 1):]


def _causes_text(causes: dict | None) -> str | None:
    """«причины: 3 × 429, 1 × сессия, 2 × код» по сводке get_report (ключи по причинам)."""
    if not causes:
        return None
    parts = [
        f"{int(causes.get(c, 0) or 0)} × {CAUSE_LABELS[c]}"
        for c in ("throttling", "session", "stand", "code")
        if int(causes.get(c, 0) or 0) > 0
    ]
    return "причины: " + ", ".join(parts) if parts else None


def _draw_header(ax, run: dict, causes: dict | None = None) -> None:
    _blank_axes(ax)
    run = run or {}
    project = run.get("project") or "—"
    stand = run.get("stand") or "без стенда"
    marker = run.get("marker") or "все"
    run_id = run.get("id")
    status = run.get("status")
    label = run.get("label")

    title = f"Прогон #{run_id} · {project}" if run_id is not None else str(project)
    if label:
        title += f" · {label}"
    ax.text(0.0, 0.80, title, transform=ax.transAxes, ha="left", va="center",
            color=INK_PRIMARY, fontsize=19, fontweight="bold")
    if status:
        status_ru = RUN_STATUS_RU.get(status, str(status))
        ax.text(1.0, 0.80, status_ru.upper(), transform=ax.transAxes, ha="right", va="center",
                color=RUN_STATUS_COLORS.get(status, INK_MUTED), fontsize=14, fontweight="bold")

    meta = f"стенд: {stand}   ·   набор: {marker}"
    period = f"{fmt_dt(run.get('started'))} → {fmt_dt(run.get('finished'))}"
    ax.text(0.0, 0.47, meta, transform=ax.transAxes, ha="left", va="center",
            color=INK_SECONDARY, fontsize=11)
    ax.text(1.0, 0.47, period, transform=ax.transAxes, ha="right", va="center",
            color=INK_SECONDARY, fontsize=11)

    rate = pass_rate(run.get("counts"))
    kpis = [f"длительность: {fmt_run_duration(run.get('duration'))}"]
    if rate is not None:
        kpis.append(f"pass rate: {rate} %")
    causes_text = _causes_text(causes)
    if causes_text:
        kpis.append(causes_text)
    ax.text(0.0, 0.14, "   ·   ".join(kpis), transform=ax.transAxes, ha="left", va="center",
            color=INK_MUTED, fontsize=11)


def _visible_statuses(counts: dict) -> list[str]:
    return [s for s in STATUSES if int(counts.get(s, 0) or 0) > 0]


def _draw_donut(ax, counts: dict) -> None:
    _blank_axes(ax)
    counts = counts or {}
    total = sum(int(counts.get(s, 0) or 0) for s in STATUSES)
    visible = _visible_statuses(counts)
    if total <= 0 or not visible:
        _title(ax, "Итог")
        _placeholder(ax)
        return

    sizes = [int(counts.get(s, 0) or 0) for s in visible]
    colors = [STATUS_COLORS[s] for s in visible]
    ax.pie(
        sizes,
        colors=colors,
        startangle=90,
        counterclock=False,
        wedgeprops={"width": 0.34, "edgecolor": SURFACE, "linewidth": 2},
    )
    rate = pass_rate(counts)
    ax.text(0, 0.10, f"{rate if rate is not None else 0} %", ha="center", va="center",
            color=INK_PRIMARY, fontsize=26, fontweight="bold")
    ax.text(0, -0.20, f"pass rate · {total} тестов", ha="center", va="center",
            color=INK_MUTED, fontsize=10)

    handles = [plt.Line2D([0], [0], marker="o", linestyle="", color=STATUS_COLORS[s], markersize=8)
               for s in visible]
    labels = [f"{s}: {int(counts.get(s, 0) or 0)}" for s in visible]
    ax.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, -0.30), ncol=2,
              frameon=False, labelcolor=INK_SECONDARY, fontsize=9)
    _title(ax, "Итог")
    ax.set_aspect("equal")


def _prepare_history(history: list[dict], limit: int) -> list[dict]:
    items = [h for h in (history or []) if isinstance(h, dict)]
    items = sorted(items, key=lambda h: (str(h.get("started") or ""), h.get("id") or 0))
    return items[-limit:] if limit else items


def trend_label(run: dict) -> str:
    """«#96 · 19.10» — как RunReportLogic.trendLabel в окне прогона."""
    run_id = run.get("id")
    id_part = f"#{run_id}" if run_id is not None else ""
    started = str(run.get("started") or "")
    if len(started) >= 10 and started[4] == "-" and started[7] == "-":
        date_part = f"{started[8:10]}.{started[5:7]}"
        return f"{id_part} · {date_part}" if id_part else date_part
    return id_part


def _draw_trend(ax, history: list[dict], limit: int) -> None:
    _blank_axes(ax)
    items = _prepare_history(history, limit)
    if not items:
        _title(ax, "Тренд")
        _placeholder(ax)
        return

    n = len(items)
    x = list(range(n))
    passed = [int((h.get("counts") or {}).get("passed", 0) or 0) for h in items]
    failed = [int((h.get("counts") or {}).get("failed", 0) or 0) + int((h.get("counts") or {}).get("broken", 0) or 0)
              for h in items]
    width = 0.38

    ax.set_facecolor(SURFACE)
    ax.bar([i - width / 2 for i in x], passed, width=width, color=STATUS_COLORS["passed"], label="passed")
    ax.bar([i + width / 2 for i in x], failed, width=width, color=STATUS_COLORS["failed"], label="failed+broken")
    ax.set_xticks(x)
    ax.set_xticklabels([trend_label(h) for h in items], rotation=45, ha="right",
                        fontsize=8, color=INK_MUTED)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=5))
    ax.tick_params(axis="y", colors=INK_MUTED, labelsize=9, length=0)
    ax.tick_params(axis="x", length=0)
    ax.yaxis.grid(True, color=GRIDLINE, linewidth=0.8)
    ax.set_axisbelow(True)
    for name in ("top", "right", "left"):
        ax.spines[name].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    ax.spines["bottom"].set_visible(True)
    # легенда над осью справа от заголовка — внутри оси она ложилась на самый высокий столбик
    ax.legend(loc="lower right", bbox_to_anchor=(1.0, 1.0), frameon=False,
              labelcolor=INK_SECONDARY, fontsize=9, ncol=2, borderaxespad=0.2)
    _title(ax, "Тренд по стенду")


def _group_failed(tests: list[dict]) -> dict[str, int]:
    groups: dict[str, int] = {}
    for t in tests:
        if t.get("status") in ("failed", "broken"):
            key = _module_of(t.get("name") or "")
            groups[key] = groups.get(key, 0) + 1
    return groups


def _draw_longest_or_failed(ax, results: list[dict], repeat: int | None = 1) -> None:
    _blank_axes(ax)
    tests = allure_report.final_attempts([t for t in (results or []) if isinstance(t, dict)], repeat)
    timed = [t for t in tests if isinstance(t.get("duration"), (int, float))]

    if timed:
        top = sorted(timed, key=lambda t: t["duration"], reverse=True)[:TOP_N]
        top = list(reversed(top))
        names = [_truncate(short_test_name(t.get("nodeid") or t.get("name") or "")) for t in top]
        values = [float(t["duration"]) for t in top]
        colors = [STATUS_COLORS.get(t.get("status"), INK_MUTED) for t in top]
        title = f"Топ-{TOP_N} самых долгих тестов"
        labels = [" " + fmt_test_duration(v) for v in values]
    else:
        groups = _group_failed(tests)
        if not groups:
            _title(ax, f"Топ-{TOP_N} самых долгих тестов")
            _placeholder(ax)
            return
        top = sorted(groups.items(), key=lambda kv: kv[1], reverse=True)[:TOP_N]
        top = list(reversed(top))
        names = [_truncate(k) for k, _ in top]
        values = [float(v) for _, v in top]
        colors = [STATUS_COLORS["failed"]] * len(values)
        title = "Топ упавших модулей (failed/broken)"
        labels = [f" {int(v)}" for v in values]

    ax.set_facecolor(SURFACE)
    y = list(range(len(values)))
    ax.barh(y, values, color=colors, height=0.6)
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=9, color=INK_SECONDARY)
    for i, v, label in zip(y, values, labels):
        ax.text(v, i, label, va="center", ha="left", color=INK_PRIMARY, fontsize=9)
    ax.set_xticks([])
    ax.tick_params(axis="y", length=0)
    ax.xaxis.grid(True, color=GRIDLINE, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_xlim(0, max(values) * 1.18 if values else 1)
    for name in ("top", "right", "left", "bottom"):
        ax.spines[name].set_visible(False)
    _title(ax, title)


# ------------------------------------------------------------------ портретный макет под телефон
# Telegram показывает фото в чате шириной ~300 pt: на широком макете 1200×1400 подписи
# тренда и названия тестов не читались без зума (макет на телефоне, 22.10.2026).
# Портрет 1080×1920 с крупным шрифтом: шапка, KPI-плитки, кольцо + счётчики цифрами,
# тренд во всю ширину, топ тестов с названием над полоской.
MOBILE_W, MOBILE_H = 1080, 1920
MOBILE_TOP_N = 6  # 8 строк в карточку 0.27 высоты не влезают без наложений
F_TITLE, F_STATUS, F_META, F_KPI_VALUE, F_KPI_LABEL = 30, 22, 19, 34, 17
F_SECTION, F_TICK, F_BODY, F_COUNT = 22, 16, 18, 40


def _mobile_card(fig: plt.Figure, rect: tuple[float, float, float, float], title: str | None = None):
    """Карточка с заголовком-секцией в левом верхнем углу (как .card h3 в вебе)."""
    _card(fig, rect)
    if title:
        x0, y0, w, h = rect
        fig.text(x0 + 0.03, y0 + h - 0.016, title, ha="left", va="top",
                 fontsize=F_SECTION, fontweight="bold", color=INK_PRIMARY)


def _draw_mobile_header(fig: plt.Figure, rect, run: dict) -> None:
    _card(fig, rect)
    x0, y0, w, h = rect
    run = run or {}
    run_id = run.get("id")
    project = run.get("project") or "—"
    status = run.get("status")
    label = run.get("label")
    title = f"Прогон #{run_id} · {project}" if run_id is not None else str(project)
    fig.text(x0 + 0.03, y0 + h - 0.02, title, ha="left", va="top",
             fontsize=F_TITLE, fontweight="bold", color=INK_PRIMARY)
    if label:
        fig.text(x0 + 0.03, y0 + h - 0.052, str(label), ha="left", va="top",
                 fontsize=F_META, color=INK_SECONDARY)
    if status:
        status_ru = RUN_STATUS_RU.get(status, str(status)).upper()
        color = RUN_STATUS_COLORS.get(status, INK_MUTED)
        fig.text(x0 + w - 0.03, y0 + h - 0.022, status_ru, ha="right", va="top",
                 fontsize=F_STATUS, fontweight="bold", color=color,
                 bbox={"boxstyle": "round,pad=0.45,rounding_size=0.8", "facecolor": SURFACE,
                       "edgecolor": color, "linewidth": 1.5})
    stand = run.get("stand") or "без стенда"
    marker = run.get("marker") or "все"
    fig.text(x0 + 0.03, y0 + 0.018, f"стенд: {stand}   ·   набор: {marker}", ha="left", va="bottom",
             fontsize=F_META, color=INK_SECONDARY)
    period = f"{fmt_dt(run.get('started'))} → {fmt_dt(run.get('finished'))}"
    fig.text(x0 + w - 0.03, y0 + 0.018, period, ha="right", va="bottom",
             fontsize=F_META, color=INK_MUTED)


def _draw_kpi_tile(fig: plt.Figure, rect, value: str, label: str, color: str = INK_PRIMARY) -> None:
    _card(fig, rect)
    x0, y0, w, h = rect
    # «12 × 429, 3 × код» в плитку ~300 px крупным шрифтом не влезает — размер по длине
    n = len(value)
    size = F_KPI_VALUE if n <= 10 else F_KPI_VALUE - 8 if n <= 14 else F_KPI_VALUE - 14
    fig.text(x0 + w / 2, y0 + h * 0.60, value, ha="center", va="center",
             fontsize=size, fontweight="bold", color=color)
    fig.text(x0 + w / 2, y0 + h * 0.22, label, ha="center", va="center",
             fontsize=F_KPI_LABEL, color=INK_MUTED)


def _draw_mobile_donut(ax, counts: dict) -> None:
    _blank_axes(ax)
    counts = counts or {}
    total = sum(int(counts.get(s, 0) or 0) for s in STATUSES)
    visible = _visible_statuses(counts)
    if total <= 0 or not visible:
        _placeholder(ax)
        return
    ax.pie(
        [int(counts.get(s, 0) or 0) for s in visible],
        colors=[STATUS_COLORS[s] for s in visible],
        startangle=90, counterclock=False,
        wedgeprops={"width": 0.28, "edgecolor": SURFACE, "linewidth": 3},
    )
    rate = pass_rate(counts)
    ax.text(0, 0.14, f"{rate if rate is not None else 0} %", ha="center", va="center",
            color=INK_PRIMARY, fontsize=F_COUNT, fontweight="bold")
    ax.text(0, -0.30, f"{total} тестов", ha="center", va="center", color=INK_MUTED, fontsize=F_BODY - 3)
    ax.set_aspect("equal")


def _draw_count_tiles(fig: plt.Figure, rect, counts: dict) -> None:
    """2×2 плитки passed/failed/broken/skipped цифрами — заметнее легенды под кольцом."""
    x0, y0, w, h = rect
    counts = counts or {}
    gap = 0.012
    tw, th = (w - gap) / 2, (h - gap) / 2
    cells = [("passed", 0, 1), ("failed", 1, 1), ("broken", 0, 0), ("skipped", 1, 0)]
    for status, col, row in cells:
        cx, cy = x0 + col * (tw + gap), y0 + row * (th + gap)
        value = int(counts.get(status, 0) or 0)
        color = STATUS_COLORS[status] if value else INK_MUTED
        fig.patches.append(FancyBboxPatch(
            (cx, cy), tw, th, boxstyle="round,pad=0,rounding_size=0.01", transform=fig.transFigure,
            facecolor=PAGE, edgecolor=GRIDLINE, linewidth=1, zorder=-1,
        ))
        fig.text(cx + tw / 2, cy + th * 0.60, str(value), ha="center", va="center",
                 fontsize=F_COUNT - 6, fontweight="bold", color=color)
        fig.text(cx + tw / 2, cy + th * 0.22, status, ha="center", va="center",
                 fontsize=F_KPI_LABEL, color=INK_MUTED)


def _draw_mobile_trend(ax, history: list[dict], limit: int) -> None:
    _blank_axes(ax)
    items = _prepare_history(history, limit)
    if not items:
        _placeholder(ax)
        return
    x = list(range(len(items)))
    passed = [int((h.get("counts") or {}).get("passed", 0) or 0) for h in items]
    failed = [int((h.get("counts") or {}).get("failed", 0) or 0) + int((h.get("counts") or {}).get("broken", 0) or 0)
              for h in items]
    width = 0.38
    ax.set_facecolor(SURFACE)
    ax.bar([i - width / 2 for i in x], passed, width=width, color=STATUS_COLORS["passed"], label="passed")
    ax.bar([i + width / 2 for i in x], failed, width=width, color=STATUS_COLORS["failed"], label="failed+broken")
    ax.set_xticks(x)
    ax.set_xticklabels([trend_label(h) for h in items], rotation=45, ha="right", fontsize=F_TICK, color=INK_MUTED)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=4))
    ax.tick_params(axis="y", colors=INK_MUTED, labelsize=F_TICK, length=0)
    ax.tick_params(axis="x", length=0)
    ax.yaxis.grid(True, color=GRIDLINE, linewidth=1)
    ax.set_axisbelow(True)
    for name in ("top", "right", "left"):
        ax.spines[name].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    ax.spines["bottom"].set_visible(True)
    ax.legend(loc="lower right", bbox_to_anchor=(1.0, 1.0), frameon=False,
              labelcolor=INK_SECONDARY, fontsize=F_TICK, ncol=2, borderaxespad=0.2)


def _draw_mobile_top(ax, results: list[dict], repeat: int | None) -> str:
    """Топ самых долгих тестов: название над полоской во всю ширину (на телефоне
    колонка с названиями слева не читается). Возвращает заголовок секции."""
    _blank_axes(ax)
    tests = allure_report.final_attempts([t for t in (results or []) if isinstance(t, dict)], repeat)
    timed = [t for t in tests if isinstance(t.get("duration"), (int, float))]
    if timed:
        top = sorted(timed, key=lambda t: t["duration"], reverse=True)[:MOBILE_TOP_N]
        names = [_truncate(short_test_name(t.get("nodeid") or t.get("name") or ""), 52) for t in top]
        values = [float(t["duration"]) for t in top]
        colors = [STATUS_COLORS.get(t.get("status"), INK_MUTED) for t in top]
        labels = [fmt_test_duration(v) for v in values]
        title = f"Топ-{len(top)} самых долгих тестов"
    else:
        groups = _group_failed(tests)
        if not groups:
            _placeholder(ax)
            return "Самые долгие тесты"
        top = sorted(groups.items(), key=lambda kv: kv[1], reverse=True)[:MOBILE_TOP_N]
        names = [_truncate(k, 52) for k, _ in top]
        values = [float(v) for _, v in top]
        colors = [STATUS_COLORS["failed"]] * len(values)
        labels = [str(int(v)) for v in values]
        title = "Топ упавших модулей (failed/broken)"
    ax.set_facecolor(SURFACE)
    n = len(values)
    vmax = max(values) or 1.0
    ax.set_xlim(0, vmax * 1.22)
    ax.set_ylim(-0.6, n - 0.2)
    for i, (name, v, color, label) in enumerate(zip(names, values, colors, labels)):
        y = n - 1 - i
        ax.text(0, y + 0.42, name, ha="left", va="center", fontsize=F_BODY, color=INK_SECONDARY)
        ax.barh(y, v, height=0.34, color=color, align="center")
        ax.text(v + vmax * 0.015, y, label, ha="left", va="center", fontsize=F_BODY,
                fontweight="bold", color=INK_PRIMARY)
    return title


def _build_mobile_report_png(run: dict, history: list[dict], results: list[dict], causes: dict | None) -> bytes:
    _apply_rc()
    fig = _new_figure(MOBILE_W, MOBILE_H)
    run = run or {}
    counts = run.get("counts") or {}
    M = 0.04  # поля
    W = 1 - 2 * M

    _draw_mobile_header(fig, (M, 0.865, W, 0.115), run)

    rate = pass_rate(counts)
    causes_text = _causes_text(causes)
    kpis = [
        (fmt_run_duration(run.get("duration")), "длительность", INK_PRIMARY),
        (f"{rate} %" if rate is not None else "—", "pass rate",
         STATUS_COLORS["passed"] if (rate or 0) >= 90 else STATUS_COLORS["broken"] if (rate or 0) >= 70 else STATUS_COLORS["failed"]),
        ((causes_text or "").replace("причины: ", "")
         or f"{sum(int(counts.get(s, 0) or 0) for s in STATUSES)}",
         "причины падений" if causes_text else "тестов", INK_PRIMARY),
    ]
    gap = 0.015
    tw = (W - 2 * gap) / 3
    for i, (value, label, color) in enumerate(kpis):
        _draw_kpi_tile(fig, (M + i * (tw + gap), 0.785, tw, 0.065), value, label, color)

    # Итог: кольцо слева, плитки счётчиков справа
    _mobile_card(fig, (M, 0.585, W, 0.185), "Итог")
    donut_ax = fig.add_axes((M + 0.02, 0.595, 0.40, 0.15))
    donut_ax.set_zorder(1)
    _draw_mobile_donut(donut_ax, counts)
    _draw_count_tiles(fig, (M + 0.46, 0.60, W - 0.49, 0.145), counts)

    # подписи тиков тренда (поворот 45°) уходят на ~0.06 ниже оси — ось поднята,
    # чтобы они остались внутри карточки, а не легли на следующую
    _mobile_card(fig, (M, 0.355, W, 0.215), "Тренд по стенду")
    trend_ax = fig.add_axes((M + 0.055, 0.425, W - 0.08, 0.105))
    trend_ax.set_zorder(1)
    _draw_mobile_trend(trend_ax, history, TREND_LIMIT)

    top_ax = fig.add_axes((M + 0.03, 0.035, W - 0.06, 0.27))
    top_ax.set_zorder(1)
    title = _draw_mobile_top(top_ax, results, run.get("repeat") or 1)
    _mobile_card(fig, (M, 0.02, W, 0.32), title)

    return _fig_to_png_bytes(fig)


def build_report_png(run: dict, history: list[dict], results: list[dict], causes: dict | None = None,
                     layout: str = "mobile") -> bytes:
    """causes — сводка по причинам из get_report (ключи throttling/session/stand/code/total);
    без неё шапка просто не показывает строку причин. layout: «mobile» (по умолчанию,
    портрет 1080×1920 под Telegram на телефоне) или «wide» (1200×1400, как окно прогона
    на десктопе — для share-страницы)."""
    if layout == "mobile":
        return _build_mobile_report_png(run, history, results, causes)
    _apply_rc()
    fig = _new_figure(1200, 1400)
    # Раскладка в долях фигуры (как сетка карточек окна прогона): шапка во всю
    # ширину, кольцо и тренд рядом, топ-10 во всю ширину с широким полем слева
    # под названия тестов.
    header_ax = _card_axes(fig, (0.04, 0.85, 0.92, 0.12), (0.02, 0.01, 0.02, 0.01))
    _draw_header(header_ax, run or {}, causes)

    donut_ax = _card_axes(fig, (0.04, 0.46, 0.44, 0.35), (0.03, 0.075, 0.03, 0.045))
    _draw_donut(donut_ax, (run or {}).get("counts") or {})

    trend_ax = _card_axes(fig, (0.52, 0.46, 0.44, 0.35), (0.045, 0.065, 0.02, 0.045))
    _draw_trend(trend_ax, history, limit=TREND_LIMIT)

    bottom_ax = _card_axes(fig, (0.04, 0.04, 0.92, 0.38), (0.27, 0.02, 0.03, 0.045))
    _draw_longest_or_failed(bottom_ax, results, (run or {}).get("repeat") or 1)

    return _fig_to_png_bytes(fig)


def build_trend_png(history: list[dict]) -> bytes:
    _apply_rc()
    fig = _new_figure(1200, 420)
    ax = _card_axes(fig, (0.03, 0.04, 0.94, 0.92), (0.035, 0.2, 0.02, 0.1))
    _draw_trend(ax, history, limit=TREND_PNG_LIMIT)
    return _fig_to_png_bytes(fig)
