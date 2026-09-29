"""Собирает реальные данные test_hub для будущих макетов «как предлагаем»
визуального аудита (docs/missions/2026-09-29_visual_audit.md).

Ничего не выдумывает и не пересчитывает сам — читает через уже готовые API
живого test_hub (тот же сервер, что рисует текущий UI), поэтому числа тут
ровно те же, что видел бы qa на реальных страницах. Источник — копия боевой
workspace/test_hub.db (см. README.md рядом), поднятая на localhost:8711
на время аудита; после работы сервер остановлен, копия БД удалена.

Запуск (сервер должен быть поднят, вход qa/qa):
    python3 docs/missions/redesign/visual_audit/collect_data.py > \
        docs/missions/redesign/visual_audit/data.snapshot.json

Реальные проекты в БД на момент сбора: VSHGU (2 стенда, 20 прогонов,
21.09-28.09.2026 — самый полный источник флаки/xfail/покрытия/статистики),
Velo_bot и bike_fit (стенды уже удалены из проекта, но история прогонов
14.09-25.09.2026 осталась — используются только для общего таймлайна
активности по дням) и Demo (только что засеян в этой копии БД, реальных
прогонов ещё не было — фиксируем пустое состояние как есть).
"""
from __future__ import annotations

import json
import urllib.request
from urllib.error import HTTPError

BASE_URL = "http://127.0.0.1:8711"
MAIN_PROJECT = "VSHGU"          # самый полный по данным, см. docstring и README.md
TIMELINE_PROJECTS = ["VSHGU", "Velo_bot", "bike_fit"]  # для общего таймлайна по дням
ALL_PROJECTS = ["VSHGU", "Velo_bot", "bike_fit", "Demo"]


def login() -> str:
    data = json.dumps({"login": "qa", "password": "qa"}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/api/login", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=10)
    cookie = resp.getheader("Set-Cookie", "")
    token = cookie.split("th_session=", 1)[1].split(";", 1)[0]
    return token


def get(token: str, path: str):
    req = urllib.request.Request(
        f"{BASE_URL}{path}", headers={"Cookie": f"th_session={token}"}
    )
    try:
        return json.loads(urllib.request.urlopen(req, timeout=60).read())
    except HTTPError as exc:
        return {"_error": exc.code, "_path": path}


def daily_timeline(token: str) -> list[dict]:
    """Число прогонов и passed/failed по дням, по всем проектам с реальной
    историей — для таймлайна «История прогонов». Один проект (VSHGU) даёт
    только ~7 дней реальных данных, вместе с Velo_bot/bike_fit набирается
    ~2 недели (14.09-28.09.2026) — используем это как честную замену
    «минимум 2-4 недели» из миссии (см. README.md, раздел про ограничения)."""
    by_day: dict[str, dict] = {}
    for project in TIMELINE_PROJECTS:
        runs = get(token, f"/api/projects/{project}/runs")
        if isinstance(runs, dict):  # _error
            continue
        for r in runs:
            day = r["started"][:10]
            bucket = by_day.setdefault(day, {"date": day, "runs": 0, "passed": 0, "failed": 0, "projects": {}})
            bucket["runs"] += 1
            counts = r["counts"]
            total = sum(counts.values())
            bucket["passed"] += counts.get("passed", 0)
            bucket["failed"] += counts.get("failed", 0) + counts.get("broken", 0)
            proj_bucket = bucket["projects"].setdefault(project, {"runs": 0, "status": []})
            proj_bucket["runs"] += 1
            proj_bucket["status"].append(r["status"])
    return sorted(by_day.values(), key=lambda b: b["date"])


def project_card(token: str, name: str, color: str, stands: list) -> dict:
    """Данные для карточки на projects.html: кольцо последнего прогона,
    спарклайн за 10 прогонов, светофор, «что важно» одной строкой."""
    runs = get(token, f"/api/projects/{name}/runs")
    if isinstance(runs, dict):
        runs = []
    last10 = runs[:10]
    last = last10[0] if last10 else None
    flaky_count = None
    if name != "Demo":
        flaky = get(token, f"/api/projects/{name}/flaky?min_runs=3")
        flaky_count = len(flaky.get("items", [])) if isinstance(flaky, dict) else None
    return {
        "name": name, "color": color, "stands": len(stands),
        "last_run": last,
        "history_10": [
            {"id": r["id"], "status": r["status"], "started": r["started"],
             "passed": r["counts"].get("passed", 0),
             "failed": r["counts"].get("failed", 0) + r["counts"].get("broken", 0),
             "skipped": r["counts"].get("skipped", 0)}
            for r in last10
        ],
        "flaky_count": flaky_count,
    }


def schedule_history_from_runs(runs: list[dict]) -> list[dict]:
    """В schedules нет истории выполнения за неделю — только last_run_id
    (см. README.md, раздел «Чего нет в данных»). Честная замена: прогоны,
    запущенные сервисным логином tg_bot, — это и есть прогоны по расписанию
    (см. app/tg_bot.py, TH_TG_SERVICE_LOGIN), их реальные даты/статусы дают
    календарную историю расписания."""
    return [
        {"id": r["id"], "started": r["started"], "status": r["status"],
         "stand": r["stand"], "duration": r["duration"]}
        for r in runs if r["requested_by"] == "tg_bot"
    ]


def main() -> None:
    token = login()
    projects_meta = {p["name"]: p for p in get(token, "/api/projects")}

    projects = [
        project_card(token, name, projects_meta[name]["color"], projects_meta[name]["stands"])
        for name in ALL_PROJECTS if name in projects_meta
    ]

    vshgu_runs = get(token, f"/api/projects/{MAIN_PROJECT}/runs")
    vshgu = {
        "runs_last20": vshgu_runs,
        "flaky": get(token, f"/api/projects/{MAIN_PROJECT}/flaky?min_runs=3"),
        "xfail": get(token, f"/api/projects/{MAIN_PROJECT}/xfail"),
        "schedules": get(token, f"/api/projects/{MAIN_PROJECT}/schedules"),
        "schedule_history": schedule_history_from_runs(vshgu_runs),
        "coverage": get(token, f"/api/projects/{MAIN_PROJECT}/coverage"),
        "stats_develop": get(token, f"/api/projects/{MAIN_PROJECT}/stats?stand=develop"),
    }

    result = {
        "meta": {
            "generated_from": "живой test_hub (копия боевой workspace/test_hub.db) на localhost:8711",
            "main_project": MAIN_PROJECT,
            "note": "См. docstring этого файла и README.md рядом — что реально есть/чего нет в данных.",
        },
        "projects": projects,
        "runs_timeline_daily": daily_timeline(token),
        MAIN_PROJECT.lower(): vshgu,
    }
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
