import secrets

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from .. import store

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    login: str
    password: str


def _user_out(user: store.User) -> dict:
    return {"id": user["id"], "login": user["login"], "name": user["name"], "role": user["role"]}


@router.post("/login")
def login(body: LoginRequest) -> dict:
    user = store.find_user_by_login(body.login)
    if user is None or user["password"] != body.password:
        raise HTTPException(status_code=401, detail="неверный логин или пароль")
    token = secrets.token_hex(16)
    store.TOKENS[token] = user["id"]
    return {"token": token, "user": _user_out(user)}


@router.get("/me")
def me(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="нет токена")
    token = authorization.removeprefix("Bearer ")
    user_id = store.TOKENS.get(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="токен недействителен")
    return _user_out(store.USERS[user_id])
