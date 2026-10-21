"""REST API вкладки «Данные» проекта — генерация тестовых данных на стенде и их
удаление через CLI проекта тестов (app/core/datagen.py). Все методы — роль qa
(superadmin проходит require_roles автоматически), как у расписаний: создание и
удаление данных на стендах — действия QA."""
import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from ..core import datagen
from ..deps import get_db, require_roles
from ..schemas import DataBatch, DataBatchCreate, DataBatchDetail, DataScenariosResponse

router = APIRouter(prefix="/api/projects", tags=["datagen"])

# Префикс попадает в имена сущностей на стенде и в аргумент CLI — только буквы/цифры/_/-,
# чтобы не тащить в имена кавычки и пробелы.
_PREFIX_RE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")


def _get_project_or_404(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row


def _get_batch_or_404(conn: sqlite3.Connection, project: str, batch_id: int) -> sqlite3.Row:
    row = datagen.get_batch(conn, project, batch_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
    return row


def _check_stand(conn: sqlite3.Connection, project: str, stand: str | None) -> None:
    if stand is None:
        return
    row = conn.execute("SELECT 1 FROM stands WHERE project = ? AND name = ?", (project, stand)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stand not found")


@router.get("/{name}/data/scenarios")
async def list_scenarios(
    name: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> DataScenariosResponse:
    project = _get_project_or_404(conn, name)
    if not datagen.supports(project["path"]):
        return DataScenariosResponse(supported=False, scenarios=[])
    try:
        scenarios = await datagen.list_scenarios(project)
    except datagen.DatagenError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return DataScenariosResponse(supported=True, scenarios=scenarios)


@router.get("/{name}/data")
def list_batches(
    name: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> list[DataBatch]:
    _get_project_or_404(conn, name)
    return [DataBatch(**datagen.row_to_dict(row)) for row in datagen.list_batches(conn, name)]


@router.post("/{name}/data", status_code=status.HTTP_201_CREATED)
async def create_batch(
    name: str,
    body: DataBatchCreate,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_roles("qa")),
) -> DataBatch:
    project = _get_project_or_404(conn, name)
    if not datagen.supports(project["path"]):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="В проекте нет test_data_generation/generate.py — генерация данных недоступна",
        )
    if not 1 <= body.count <= datagen.MAX_COUNT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"count должен быть от 1 до {datagen.MAX_COUNT}",
        )
    prefix = (body.prefix or "").strip() or None
    if prefix is not None and not _PREFIX_RE.match(prefix):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Префикс — только буквы, цифры, «_» и «-», до 40 символов",
        )
    _check_stand(conn, name, body.stand)
    try:
        scenarios = await datagen.list_scenarios(project)
    except datagen.DatagenError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    if body.scenario not in {s["name"] for s in scenarios}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Неизвестный сценарий {body.scenario!r}",
        )
    active = datagen.active_batch(conn, name)
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Партия #{active['id']} ещё выполняется ({active['status']}) — дождитесь её завершения",
        )
    row = datagen.insert_batch(conn, name, body.stand, body.scenario, body.count, prefix, user["login"])
    datagen.schedule_create(row["id"])
    return DataBatch(**datagen.row_to_dict(row))


@router.get("/{name}/data/{batch_id}")
def get_batch(
    name: str,
    batch_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> DataBatchDetail:
    _get_project_or_404(conn, name)
    row = _get_batch_or_404(conn, name, batch_id)
    return DataBatchDetail(**datagen.row_to_dict(row, details=True))


@router.delete("/{name}/data/{batch_id}", status_code=status.HTTP_202_ACCEPTED)
async def delete_batch_data(
    name: str,
    batch_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> DataBatch:
    """Удалить созданные партией данные на стенде (--cleanup по манифесту). Сама запись
    партии остаётся со статусом deleted — это история того, что создавалось."""
    _get_project_or_404(conn, name)
    row = _get_batch_or_404(conn, name, batch_id)
    if row["status"] not in datagen.DELETABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Партию в статусе {row['status']} удалить нельзя",
        )
    if datagen.row_to_dict(row)["created_total"] == 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="В манифесте партии нет созданных сущностей")
    active = datagen.active_batch(conn, name)
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Партия #{active['id']} ещё выполняется ({active['status']}) — дождитесь её завершения",
        )
    conn.execute("UPDATE data_batches SET status = 'deleting', error = NULL WHERE id = ?", (batch_id,))
    conn.commit()
    datagen.schedule_delete(batch_id)
    return DataBatch(**datagen.row_to_dict(datagen.get_batch(conn, name, batch_id)))
