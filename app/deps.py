import sqlite3
from typing import Iterator

from fastapi import Depends, HTTPException, Request, status

from .config import settings
from .db import get_connection
from .security import verify_session_token


def get_db() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def get_current_user(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> sqlite3.Row:
    token = request.cookies.get(settings.SESSION_COOKIE)
    login = verify_session_token(token, settings.TH_SECRET, settings.SESSION_MAX_AGE) if token else None
    if not login:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    row = conn.execute("SELECT * FROM users WHERE login = ?", (login,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return row


def require_roles(*roles: str):
    def checker(user: sqlite3.Row = Depends(get_current_user)) -> sqlite3.Row:
        if user["role"] not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return user

    return checker
