"""REST API поверх app/core/youtrack.py::list_my_issues — вкладка «Задачи»:
задачи YouTrack, где исполнитель — владелец TH_YOUTRACK_TOKEN (единственный
сконфигурированный токен на весь test_hub, см. app/core/youtrack.py). Доступ —
те же роли, что у Sentry (qa, superadmin проходит через require_roles
автоматически, см. app/deps.py)."""
import sqlite3

from fastapi import APIRouter, Depends

from ..core import youtrack as youtrack_client
from ..deps import require_roles
from ..schemas import YouTrackTaskOut, YouTrackTasksResponse

router = APIRouter(prefix="/api", tags=["youtrack-tasks"])


@router.get("/youtrack/my-tasks")
def get_my_youtrack_tasks(
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> YouTrackTasksResponse:
    if not youtrack_client.is_configured():
        return YouTrackTasksResponse(connected=False, reason="YouTrack не настроен")
    try:
        tasks = youtrack_client.list_my_issues()
    except youtrack_client.YouTrackError as exc:
        return YouTrackTasksResponse(connected=False, reason=str(exc))
    return YouTrackTasksResponse(
        connected=True,
        tasks=[
            YouTrackTaskOut(
                id=t.id,
                summary=t.summary,
                project=t.project,
                status=t.status,
                updated=t.updated,
                url=t.url,
            )
            for t in tasks
        ],
    )
