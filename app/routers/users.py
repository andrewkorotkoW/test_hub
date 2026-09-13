import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from ..deps import require_roles, get_db
from ..schemas import UserCreate, UserUpdate
from ..security import hash_password

router = APIRouter(prefix="/api/users", tags=["users"])


def _user_payload(row: sqlite3.Row) -> dict:
    return {"login": row["login"], "role": row["role"], "onboarded": bool(row["onboarded"])}


def _get_user_or_404(conn: sqlite3.Connection, login: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM users WHERE login = ?", (login,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return row


@router.get("")
def list_users(
    conn: sqlite3.Connection = Depends(get_db), _user: sqlite3.Row = Depends(require_roles("qa"))
) -> list[dict]:
    rows = conn.execute("SELECT * FROM users ORDER BY login").fetchall()
    return [_user_payload(r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> dict:
    exists = conn.execute("SELECT 1 FROM users WHERE login = ?", (body.login,)).fetchone()
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already exists")
    conn.execute(
        "INSERT INTO users (login, password_hash, role, onboarded) VALUES (?, ?, ?, ?)",
        (body.login, hash_password(body.password), body.role, int(body.onboarded)),
    )
    conn.commit()
    return _user_payload(_get_user_or_404(conn, body.login))


@router.put("/{login}")
def update_user(
    login: str,
    body: UserUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> dict:
    row = _get_user_or_404(conn, login)
    password_hash = hash_password(body.password) if body.password else row["password_hash"]
    role = body.role if body.role is not None else row["role"]
    onboarded = int(body.onboarded) if body.onboarded is not None else row["onboarded"]
    conn.execute(
        "UPDATE users SET password_hash = ?, role = ?, onboarded = ? WHERE login = ?",
        (password_hash, role, onboarded, login),
    )
    conn.commit()
    return _user_payload(_get_user_or_404(conn, login))


@router.delete("/{login}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    login: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> None:
    _get_user_or_404(conn, login)
    conn.execute("DELETE FROM users WHERE login = ?", (login,))
    conn.commit()
