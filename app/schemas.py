from typing import Literal, Optional

from pydantic import BaseModel

Role = Literal["qa", "manager", "customer", "superadmin"]


class LoginRequest(BaseModel):
    login: str
    password: str


class ProjectCreate(BaseModel):
    name: str
    path: str
    venv: str = ".venv"
    use_env_flag: bool = False


class ProjectUpdate(BaseModel):
    path: Optional[str] = None
    venv: Optional[str] = None
    use_env_flag: Optional[bool] = None


class StandCreate(BaseModel):
    name: str
    url: str
    login: Optional[str] = None


class StandUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    login: Optional[str] = None


class RunCreate(BaseModel):
    stand: Optional[str] = None
    target: str = "all"
    marker: Optional[str] = None


class UserCreate(BaseModel):
    login: str
    password: str
    role: Role
    onboarded: bool = False


class UserUpdate(BaseModel):
    password: Optional[str] = None
    role: Optional[Role] = None
    onboarded: Optional[bool] = None


class AdminUserUpdate(BaseModel):
    role: Optional[Role] = None
    password: Optional[str] = None
