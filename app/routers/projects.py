import os
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from ..deps import get_current_user, get_db, require_roles
from ..schemas import ProjectCreate, ProjectUpdate, StandCreate, StandUpdate

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _stands_for(conn: sqlite3.Connection, project_name: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, name, url, login FROM stands WHERE project = ? ORDER BY name", (project_name,)
    ).fetchall()
    return [dict(r) for r in rows]


def _project_payload(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    return {
        "name": row["name"],
        "path": row["path"],
        "venv": row["venv"],
        "stands": _stands_for(conn, row["name"]),
    }


def _get_project_or_404(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row


@router.get("")
def list_projects(
    conn: sqlite3.Connection = Depends(get_db), _user: sqlite3.Row = Depends(get_current_user)
) -> list[dict]:
    rows = conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
    return [_project_payload(conn, r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_project(
    body: ProjectCreate,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> dict:
    exists = conn.execute("SELECT 1 FROM projects WHERE name = ?", (body.name,)).fetchone()
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Project already exists")
    if not os.path.isdir(body.path):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Path does not exist or is not a directory",
        )
    conn.execute(
        "INSERT INTO projects (name, path, venv, stands) VALUES (?, ?, ?, '[]')",
        (body.name, body.path, body.venv),
    )
    conn.commit()
    return _project_payload(conn, _get_project_or_404(conn, body.name))


@router.put("/{name}")
def update_project(
    name: str,
    body: ProjectUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> dict:
    row = _get_project_or_404(conn, name)
    path = body.path if body.path is not None else row["path"]
    venv = body.venv if body.venv is not None else row["venv"]
    conn.execute("UPDATE projects SET path = ?, venv = ? WHERE name = ?", (path, venv, name))
    conn.commit()
    return _project_payload(conn, _get_project_or_404(conn, name))


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    name: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> None:
    _get_project_or_404(conn, name)
    conn.execute("DELETE FROM projects WHERE name = ?", (name,))
    conn.commit()


@router.get("/{name}/stands")
def list_stands(
    name: str, conn: sqlite3.Connection = Depends(get_db), _user: sqlite3.Row = Depends(get_current_user)
) -> list[dict]:
    _get_project_or_404(conn, name)
    return _stands_for(conn, name)


@router.post("/{name}/stands", status_code=status.HTTP_201_CREATED)
def create_stand(
    name: str,
    body: StandCreate,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> dict:
    _get_project_or_404(conn, name)
    exists = conn.execute(
        "SELECT 1 FROM stands WHERE project = ? AND name = ?", (name, body.name)
    ).fetchone()
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stand already exists")
    cur = conn.execute(
        "INSERT INTO stands (project, name, url, login) VALUES (?, ?, ?, ?)",
        (name, body.name, body.url, body.login),
    )
    conn.commit()
    row = conn.execute("SELECT id, name, url, login FROM stands WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def _get_stand_or_404(conn: sqlite3.Connection, project: str, stand_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM stands WHERE id = ? AND project = ?", (stand_id, project)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stand not found")
    return row


@router.put("/{name}/stands/{stand_id}")
def update_stand(
    name: str,
    stand_id: int,
    body: StandUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> dict:
    _get_project_or_404(conn, name)
    row = _get_stand_or_404(conn, name, stand_id)
    stand_name = body.name if body.name is not None else row["name"]
    url = body.url if body.url is not None else row["url"]
    login = body.login if body.login is not None else row["login"]
    conn.execute(
        "UPDATE stands SET name = ?, url = ?, login = ? WHERE id = ?", (stand_name, url, login, stand_id)
    )
    conn.commit()
    row = conn.execute("SELECT id, name, url, login FROM stands WHERE id = ?", (stand_id,)).fetchone()
    return dict(row)


@router.delete("/{name}/stands/{stand_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stand(
    name: str,
    stand_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> None:
    _get_project_or_404(conn, name)
    _get_stand_or_404(conn, name, stand_id)
    conn.execute("DELETE FROM stands WHERE id = ?", (stand_id,))
    conn.commit()
