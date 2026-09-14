"""Суперадминка: обзор и полная выгрузка/удаление данных по всем таблицам БД.

Все эндпоинты защищены require_roles("superadmin") — это единственное место в
приложении, куда роль qa доступа не имеет (см. app/deps.py: superadmin проходит
через любой require_roles(...), но остальные роли — только через явный список).
"""
from __future__ import annotations

import shutil
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..core import runner
from ..deps import get_db, require_roles
from ..schemas import AdminUserUpdate
from ..security import hash_password

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Явный whitelist колонок на таблицу: защищает ORDER BY/поиск от SQL-инъекции
# через query-параметры (таблица/колонка всегда подставляются из этого словаря,
# никогда — из сырого пользовательского ввода) и не даёт password_hash утечь.
_TABLES: dict[str, dict] = {
    "users": {
        "columns": ["login", "role", "onboarded"],
        "search_columns": ["login", "role"],
        "pk": "login",
    },
    "projects": {
        "columns": ["name", "path", "venv", "stands"],
        "search_columns": ["name", "path", "venv"],
        "pk": "name",
    },
    "stands": {
        "columns": ["id", "project", "name", "url", "login"],
        "search_columns": ["project", "name", "url", "login"],
        "pk": "id",
    },
    "runs": {
        "columns": [
            "id", "project", "stand", "target", "status",
            "started", "finished", "duration", "requested_by", "counts",
        ],
        "search_columns": ["project", "stand", "target", "status", "requested_by"],
        "pk": "id",
    },
    "run_events": {
        "columns": ["id", "run_id", "ts", "line"],
        "search_columns": ["line"],
        "pk": "id",
    },
}


def _row_payload(table: str, row: sqlite3.Row) -> dict:
    return {col: row[col] for col in _TABLES[table]["columns"]}


def _table_or_404(table: str) -> dict:
    meta = _TABLES.get(table)
    if meta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown table")
    return meta


@router.get("/overview")
def overview(
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("superadmin")),
) -> dict:
    counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in _TABLES}
    runs_by_status = {
        row["status"]: row["c"]
        for row in conn.execute("SELECT status, COUNT(*) AS c FROM runs GROUP BY status").fetchall()
    }
    recent = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 10").fetchall()
    return {
        "counts": counts,
        "runs_by_status": runs_by_status,
        "recent_runs": [_row_payload("runs", r) for r in recent],
    }


@router.get("/{table}")
def list_table(
    table: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    q: str | None = Query(None),
    sort: str | None = Query(None),
    order: str = Query("asc"),
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("superadmin")),
) -> dict:
    meta = _table_or_404(table)
    columns = meta["columns"]

    where_sql = ""
    params: list = []
    if q:
        where_sql = "WHERE " + " OR ".join(f"{col} LIKE ?" for col in meta["search_columns"])
        params = [f"%{q}%"] * len(meta["search_columns"])

    sort_col = sort if sort in columns else meta["pk"]
    order_sql = "DESC" if order.lower() == "desc" else "ASC"

    total = conn.execute(f"SELECT COUNT(*) FROM {table} {where_sql}", params).fetchone()[0]
    offset = (page - 1) * per_page
    rows = conn.execute(
        f"SELECT * FROM {table} {where_sql} ORDER BY {sort_col} {order_sql} LIMIT ? OFFSET ?",
        [*params, per_page, offset],
    ).fetchall()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "items": [_row_payload(table, r) for r in rows],
    }


@router.put("/users/{login}")
def update_user(
    login: str,
    body: AdminUserUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("superadmin")),
) -> dict:
    row = conn.execute("SELECT * FROM users WHERE login = ?", (login,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    role = body.role if body.role is not None else row["role"]
    password_hash = hash_password(body.password) if body.password else row["password_hash"]
    conn.execute(
        "UPDATE users SET role = ?, password_hash = ? WHERE login = ?", (role, password_hash, login)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE login = ?", (login,)).fetchone()
    return _row_payload("users", row)


@router.delete("/{table}/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_row(
    table: str,
    item_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_roles("superadmin")),
) -> None:
    meta = _table_or_404(table)
    pk = meta["pk"]

    if table == "users":
        if item_id == user["login"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete yourself")
        row = conn.execute("SELECT 1 FROM users WHERE login = ?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        conn.execute("DELETE FROM users WHERE login = ?", (item_id,))
        conn.commit()
        return

    if table == "projects":
        row = conn.execute("SELECT 1 FROM projects WHERE name = ?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        conn.execute("DELETE FROM projects WHERE name = ?", (item_id,))
        conn.commit()
        return

    # stands, runs, run_events используют числовой id
    try:
        numeric_id = int(item_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    if table == "stands":
        row = conn.execute("SELECT 1 FROM stands WHERE id = ?", (numeric_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        conn.execute("DELETE FROM stands WHERE id = ?", (numeric_id,))
        conn.commit()
        return

    if table == "runs":
        row = conn.execute("SELECT status FROM runs WHERE id = ?", (numeric_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        if row["status"] == "running":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Cannot delete a running run"
            )
        conn.execute("DELETE FROM run_events WHERE run_id = ?", (numeric_id,))
        conn.execute("DELETE FROM runs WHERE id = ?", (numeric_id,))
        conn.commit()
        shutil.rmtree(runner.allure_dir(numeric_id), ignore_errors=True)
        return

    if table == "run_events":
        row = conn.execute(f"SELECT 1 FROM run_events WHERE {pk} = ?", (numeric_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        conn.execute(f"DELETE FROM run_events WHERE {pk} = ?", (numeric_id,))
        conn.commit()
        return
