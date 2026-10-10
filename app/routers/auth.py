import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status

from ..config import settings
from ..core.test_cases import _EXTENSION_MIME_TYPES, _IMAGE_MIME_EXTENSIONS
from ..deps import get_current_user, get_db
from ..schemas import LoginRequest, MeUpdate, RegisterRequest
from ..security import create_session_token, hash_password, verify_password

router = APIRouter(prefix="/api", tags=["auth"])

# Отдельная ветка диска от TESTCASES_DIR (app/core/test_cases.py) — аватар не
# привязан к проекту/кейсу, просто <login>.<ext>, перезаписывается при повторной
# загрузке (см. upload_my_avatar).
AVATARS_DIR = settings.WORKSPACE_DIR / "avatars"


def _login_payload(user: sqlite3.Row) -> dict:
    """Старая (не расширенная) форма — только для POST /api/login, чей ответ
    покрыт строгим сравнением словаря в tests/test_auth.py."""
    return {"login": user["login"], "role": user["role"], "onboarded": bool(user["onboarded"])}


def _me_payload(user: sqlite3.Row) -> dict:
    return {
        "login": user["login"],
        "role": user["role"],
        "onboarded": bool(user["onboarded"]),
        "full_name": user["full_name"],
        "position": user["position"],
        "project": user["project"],
        "status": user["status"],
        "avatar_url": "/api/me/avatar" if user["avatar_filename"] else None,
    }


def _avatar_response(conn: sqlite3.Connection, login: str) -> Response:
    row = conn.execute("SELECT avatar_filename FROM users WHERE login = ?", (login,)).fetchone()
    if not row or not row["avatar_filename"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")
    path = AVATARS_DIR / row["avatar_filename"]
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")
    mime = _EXTENSION_MIME_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return Response(content=path.read_bytes(), media_type=mime)


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    exists = conn.execute("SELECT 1 FROM users WHERE login = ?", (body.login,)).fetchone()
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already exists")
    if body.project is not None:
        project_exists = conn.execute("SELECT 1 FROM projects WHERE name = ?", (body.project,)).fetchone()
        if not project_exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    conn.execute(
        "INSERT INTO users (login, password_hash, role, onboarded, full_name, position, project, status) "
        "VALUES (?, ?, 'customer', 0, ?, ?, ?, 'pending')",
        (body.login, hash_password(body.password), body.full_name, body.position, body.project),
    )
    conn.commit()
    return {"status": "pending"}


@router.post("/login")
def login(body: LoginRequest, response: Response, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    row = conn.execute("SELECT * FROM users WHERE login = ?", (body.login,)).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if row["status"] != "active":
        detail = "Заявка ещё не одобрена" if row["status"] == "pending" else "Заявка отклонена"
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
    token = create_session_token(row["login"], settings.TH_SECRET)
    response.set_cookie(
        settings.SESSION_COOKIE,
        token,
        max_age=settings.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return _login_payload(row)


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(settings.SESSION_COOKIE)
    return {"ok": True}


@router.get("/me")
def me(user: sqlite3.Row = Depends(get_current_user)) -> dict:
    return _me_payload(user)


@router.put("/me")
def update_me(
    body: MeUpdate,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    if body.project is not None:
        exists = conn.execute("SELECT 1 FROM projects WHERE name = ?", (body.project,)).fetchone()
        if not exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    full_name = body.full_name if body.full_name is not None else user["full_name"]
    position = body.position if body.position is not None else user["position"]
    project = body.project if body.project is not None else user["project"]
    conn.execute(
        "UPDATE users SET full_name = ?, position = ?, project = ? WHERE login = ?",
        (full_name, position, project, user["login"]),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE login = ?", (user["login"],)).fetchone()
    return _me_payload(row)


@router.post("/me/onboarded")
def set_onboarded(
    user: sqlite3.Row = Depends(get_current_user), conn: sqlite3.Connection = Depends(get_db)
) -> dict:
    conn.execute("UPDATE users SET onboarded = 1 WHERE login = ?", (user["login"],))
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE login = ?", (user["login"],)).fetchone()
    return _me_payload(row)


@router.post("/me/avatar")
async def upload_my_avatar(
    file: UploadFile = File(...),
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    raw = await file.read()
    if len(raw) > settings.TH_TESTCASE_ATTACHMENT_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Avatar exceeds TH_TESTCASE_ATTACHMENT_MAX_BYTES ({settings.TH_TESTCASE_ATTACHMENT_MAX_BYTES} bytes)",
        )
    mime = _EXTENSION_MIME_TYPES.get(Path(file.filename or "").suffix.lower())
    if mime is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported file type (PNG/JPG only)"
        )
    ext = _IMAGE_MIME_EXTENSIONS[mime]

    AVATARS_DIR.mkdir(parents=True, exist_ok=True)
    old_filename = user["avatar_filename"]
    if old_filename:
        (AVATARS_DIR / old_filename).unlink(missing_ok=True)
    new_filename = f"{user['login']}{ext}"
    (AVATARS_DIR / new_filename).write_bytes(raw)
    conn.execute("UPDATE users SET avatar_filename = ? WHERE login = ?", (new_filename, user["login"]))
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE login = ?", (user["login"],)).fetchone()
    return _me_payload(row)


@router.get("/me/avatar")
def get_my_avatar(
    user: sqlite3.Row = Depends(get_current_user), conn: sqlite3.Connection = Depends(get_db)
) -> Response:
    return _avatar_response(conn, user["login"])


@router.get("/users/{login}/avatar")
def get_user_avatar(
    login: str, _user: sqlite3.Row = Depends(get_current_user), conn: sqlite3.Connection = Depends(get_db)
) -> Response:
    return _avatar_response(conn, login)
