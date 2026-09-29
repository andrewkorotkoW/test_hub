from fastapi import APIRouter, HTTPException

from .. import store

router = APIRouter(prefix="/api/users", tags=["users"])


def _user_out(user: store.User) -> dict:
    return {"id": user["id"], "login": user["login"], "name": user["name"], "role": user["role"]}


@router.get("")
def list_users() -> list[dict]:
    return [_user_out(u) for u in store.USERS.values()]


@router.get("/{user_id}")
def get_user(user_id: int) -> dict:
    user = store.USERS.get(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="пользователь не найден")
    return _user_out(user)
