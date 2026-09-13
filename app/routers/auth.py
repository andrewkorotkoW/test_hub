import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response, status

from ..config import settings
from ..deps import get_current_user, get_db
from ..schemas import LoginRequest
from ..security import create_session_token, verify_password

router = APIRouter(prefix="/api", tags=["auth"])


def _me_payload(user: sqlite3.Row) -> dict:
    return {"login": user["login"], "role": user["role"], "onboarded": bool(user["onboarded"])}


@router.post("/login")
def login(body: LoginRequest, response: Response, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    row = conn.execute("SELECT * FROM users WHERE login = ?", (body.login,)).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_session_token(row["login"], settings.TH_SECRET)
    response.set_cookie(
        settings.SESSION_COOKIE,
        token,
        max_age=settings.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return _me_payload(row)


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(settings.SESSION_COOKIE)
    return {"ok": True}


@router.get("/me")
def me(user: sqlite3.Row = Depends(get_current_user)) -> dict:
    return _me_payload(user)


@router.post("/me/onboarded")
def set_onboarded(
    user: sqlite3.Row = Depends(get_current_user), conn: sqlite3.Connection = Depends(get_db)
) -> dict:
    conn.execute("UPDATE users SET onboarded = 1 WHERE login = ?", (user["login"],))
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE login = ?", (user["login"],)).fetchone()
    return _me_payload(row)
