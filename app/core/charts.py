"""PNG-рендер отчёта прогона и тренда на matplotlib (backend Agg, тёмная тема).

Чистые функции над структурами из app.core.allure_report / app.routers.runs::get_report
(run-payload с counts/tests, список тестов name/status/duration/message) — без записи
на диск, без сети и без обращений к БД: только bytes на выходе.

Палитра — тёмная тема из скилла dataviz (references/palette.md): поверхность/чернила/
статус-цвета для passed/failed/broken и последовательный синий для шкалы длительности.
"""
from __future__ import annotations

import io
from datetime import datetime

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  (после matplotlib.use)

STATUSES = ("passed", "failed", "broken", "skipped")

SURFACE = "#1a1a19"
PAGE = "#0d0d0d"
INK_PRIMARY = "#ffffff"
INK_SECONDARY = "#c3c2b7"
INK_MUTED = "#898781"
GRIDLINE = "#2c2c2a"
BASELINE = "#383835"

STATUS_COLORS = {
    "passed": "#0ca30c",
    "failed": "#d03b3b",
    "broken": "#ec835a",
    "skipped": INK_MUTED,
}
SEQUENTIAL_BLUE = "#3987e5"

FONT_FAMILY = ["system-ui", "Segoe UI", "DejaVu Sans", "sans-serif"]


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


def _blank_axes(ax) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def _placeholder(ax, text: str = "нет данных") -> None:
    _blank_axes(ax)
    ax.text(0.5, 0.5, text, ha="center", va="center", color=INK_MUTED, fontsize=12)


def _fmt_dt(value) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return str(value)
    return dt.strftime("%d.%m.%Y %H:%M")


def _fmt_date_short(value) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return str(value)[:10]
    return dt.strftime("%d.%m %H:%M")


def _fmt_duration(seconds) -> str:
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "—"
    minutes, secs = divmod(int(round(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}ч {minutes}м {secs}с"
    if minutes:
        return f"{minutes}м {secs}с"
    return f"{secs}с"


def _module_of(name: str) -> str:
    if not name:
        return "unknown"
    if "::" in name:
        return name.split("::", 1)[0]
    if "." in name:
        return name.rsplit(".", 1)[0]
    return name


def _truncate(name: str, limit: int = 32) -> str:
    if not name:
        return "—"
    return name if len(name) <= limit else "…" + name[-(limit - 1):]


def _draw_header(ax, run: dict) -> None:
    _blank_axes(ax)
    run = run or {}
    project = run.get("project") or "—"
    stand = run.get("stand") or "—"
    marker = run.get("marker") or "—"
    run_id = run.get("id")
    status = run.get("status")

    subtitle = f"стенд: {stand}   ·   маркер: {marker}"
    if run_id is not None:
        subtitle += f"   ·   прогон #{run_id}"
    period = f"{_fmt_dt(run.get('started'))} → {_fmt_dt(run.get('finished'))}"
    duration = f"длительность: {_fmt_duration(run.get('duration'))}"

    ax.text(0.01, 0.72, str(project), transform=ax.transAxes, ha="left", va="center",
            color=INK_PRIMARY, fontsize=20, fontweight="bold")
    ax.text(0.01, 0.28, subtitle, transform=ax.transAxes, ha="left", va="center",
            color=INK_SECONDARY, fontsize=12)
    ax.text(0.99, 0.72, period, transform=ax.transAxes, ha="right", va="center",
            color=INK_SECONDARY, fontsize=11)
    ax.text(0.99, 0.28, duration, transform=ax.transAxes, ha="right", va="center",
            color=INK_MUTED, fontsize=11)
    if status:
        ax.text(0.5, 0.72, str(status).upper(), transform=ax.transAxes, ha="center", va="center",
                color=STATUS_COLORS.get(status, INK_MUTED), fontsize=13, fontweight="bold")


def _visible_statuses(counts: dict) -> list[str]:
    visible = []
    for s in STATUSES:
        value = int(counts.get(s, 0) or 0)
        if value <= 0:
            continue
        visible.append(s)
    return visible


def _draw_donut(ax, counts: dict) -> None:
    _blank_axes(ax)
    counts = counts or {}
    total = sum(int(counts.get(s, 0) or 0) for s in STATUSES)
    visible = _visible_statuses(counts)
    if total <= 0 or not visible:
        _placeholder(ax)
        return

    sizes = [int(counts.get(s, 0) or 0) for s in visible]
    colors = [STATUS_COLORS[s] for s in visible]
    ax.pie(
        sizes,
        colors=colors,
        startangle=90,
        counterclock=False,
        wedgeprops={"width": 0.38, "edgecolor": SURFACE, "linewidth": 2},
    )
    passed = int(counts.get("passed", 0) or 0)
    pct = round(100 * passed / total)
    ax.text(0, 0.10, f"{pct}%", ha="center", va="center", color=INK_PRIMARY,
            fontsize=26, fontweight="bold")
    ax.text(0, -0.18, "passed", ha="center", va="center", color=INK_SECONDARY, fontsize=11)

    handles = [plt.Line2D([0], [0], marker="o", linestyle="", color=STATUS_COLORS[s], markersize=8)
               for s in visible]
    labels = [f"{s}: {int(counts.get(s, 0) or 0)}" for s in visible]
    ax.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, -0.32), ncol=2,
              frameon=False, labelcolor=INK_SECONDARY, fontsize=9)
    ax.set_title("Результаты", loc="left", fontsize=12, color=INK_PRIMARY, pad=10)
    ax.set_aspect("equal")


def _prepare_history(history: list[dict], limit: int) -> list[dict]:
    items = [h for h in (history or []) if isinstance(h, dict)]

    def _key(h: dict):
        started = h.get("started")
        try:
            return datetime.fromisoformat(started) if started else datetime.min
        except (TypeError, ValueError):
            return datetime.min

    items = sorted(items, key=lambda h: (_key(h), h.get("id") or 0))
    return items[-limit:] if limit else items


def _draw_trend(ax, history: list[dict], limit: int) -> None:
    _blank_axes(ax)
    items = _prepare_history(history, limit)
    if not items:
        _placeholder(ax)
        return

    n = len(items)
    x = list(range(n))
    passed = [int((h.get("counts") or {}).get("passed", 0) or 0) for h in items]
    failed = [int((h.get("counts") or {}).get("failed", 0) or 0) for h in items]
    width = 0.38

    ax.set_facecolor(SURFACE)
    ax.bar([i - width / 2 for i in x], passed, width=width, color=STATUS_COLORS["passed"], label="passed")
    ax.bar([i + width / 2 for i in x], failed, width=width, color=STATUS_COLORS["failed"], label="failed")
    ax.set_xticks(x)
    ax.set_xticklabels([_fmt_date_short(h.get("started")) for h in items], rotation=45, ha="right",
                        fontsize=8, color=INK_MUTED)
    ax.tick_params(axis="y", colors=INK_MUTED, labelsize=9)
    ax.yaxis.grid(True, color=GRIDLINE, linewidth=0.8)
    ax.set_axisbelow(True)
    for name in ("top", "right", "left"):
        ax.spines[name].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    ax.legend(loc="upper left", frameon=False, labelcolor=INK_SECONDARY, fontsize=9, ncol=2)
    ax.set_title("Тренд", loc="left", fontsize=12, color=INK_PRIMARY, pad=10)


def _group_failed(tests: list[dict]) -> dict[str, int]:
    groups: dict[str, int] = {}
    for t in tests:
        if t.get("status") in ("failed", "broken"):
            key = _module_of(t.get("name") or "")
            groups[key] = groups.get(key, 0) + 1
    return groups


def _draw_longest_or_failed(ax, results: list[dict]) -> None:
    _blank_axes(ax)
    tests = [t for t in (results or []) if isinstance(t, dict)]
    timed = [t for t in tests if isinstance(t.get("duration"), (int, float))]

    if timed:
        top = sorted(timed, key=lambda t: t["duration"], reverse=True)[:10]
        top = list(reversed(top))
        names = [_truncate(t.get("name") or "") for t in top]
        values = [float(t["duration"]) for t in top]
        colors = [SEQUENTIAL_BLUE] * len(values)
        title = "Топ-10 самых долгих тестов, с"

        def _label(v: float) -> str:
            return f" {v:.1f}с"
    else:
        groups = _group_failed(tests)
        if not groups:
            _placeholder(ax)
            return
        top = sorted(groups.items(), key=lambda kv: kv[1], reverse=True)[:10]
        top = list(reversed(top))
        names = [_truncate(k) for k, _ in top]
        values = [float(v) for _, v in top]
        colors = [STATUS_COLORS["failed"]] * len(values)
        title = "Топ упавших модулей (failed/broken)"

        def _label(v: float) -> str:
            return f" {int(v)}"

    ax.set_facecolor(SURFACE)
    y = list(range(len(values)))
    ax.barh(y, values, color=colors, height=0.6)
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=9, color=INK_SECONDARY)
    for i, v in zip(y, values):
        ax.text(v, i, _label(v), va="center", ha="left", color=INK_PRIMARY, fontsize=9)
    ax.tick_params(axis="x", colors=INK_MUTED, labelsize=9)
    ax.xaxis.grid(True, color=GRIDLINE, linewidth=0.8)
    ax.set_axisbelow(True)
    for name in ("top", "right", "left"):
        ax.spines[name].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    ax.set_title(title, loc="left", fontsize=12, color=INK_PRIMARY, pad=10)


def build_report_png(run: dict, history: list[dict], results: list[dict]) -> bytes:
    _apply_rc()
    fig = _new_figure(1200, 1500)
    gs = fig.add_gridspec(
        3, 2,
        height_ratios=[1, 2.4, 2.2],
        hspace=0.55, wspace=0.18,
        left=0.07, right=0.97, top=0.96, bottom=0.07,
    )

    header_ax = fig.add_subplot(gs[0, :])
    _draw_header(header_ax, run or {})

    donut_ax = fig.add_subplot(gs[1, 0])
    _draw_donut(donut_ax, (run or {}).get("counts") or {})

    trend_ax = fig.add_subplot(gs[1, 1])
    _draw_trend(trend_ax, history, limit=10)

    bottom_ax = fig.add_subplot(gs[2, :])
    _draw_longest_or_failed(bottom_ax, results)
    # Горизонтальные подписи здесь заметно шире, чем у остальных зон — расширяем
    # левое поле именно этой оси, не трогая раскладку донат/тренда.
    pos = bottom_ax.get_position()
    bottom_ax.set_position((0.26, pos.y0, 0.97 - 0.26, pos.height))

    return _fig_to_png_bytes(fig)


def build_trend_png(history: list[dict]) -> bytes:
    _apply_rc()
    fig = _new_figure(1200, 420)
    ax = fig.add_axes((0.06, 0.24, 0.91, 0.66))
    _draw_trend(ax, history, limit=30)
    return _fig_to_png_bytes(fig)
