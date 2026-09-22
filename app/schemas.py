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


class CoverageStandSummary(BaseModel):
    stand: str
    routes_total: int
    routes_covered: int
    percent: float


class CoverageRouteStandStatus(BaseModel):
    state: str
    run_id: Optional[int] = None


class CoverageMapRoute(BaseModel):
    name: str
    methods: list[str]
    path: str
    area: str
    tests_count: int
    shared: bool
    status: dict[str, CoverageRouteStandStatus]


class CoverageMapArea(BaseModel):
    area: str
    routes: list[CoverageMapRoute]


class CoverageSummary(BaseModel):
    project: str
    generated_at: str
    stands: list[CoverageStandSummary]
    routes_total: int
    routes_covered: int
    zero_coverage_areas: list[str]
    map: list[CoverageMapArea]


class CoverageRouteTestStatus(BaseModel):
    nodeid: str
    env: Optional[str] = None
    status: dict[str, Optional[str]]


class CoverageRouteDetail(BaseModel):
    name: str
    methods: list[str]
    path: str
    tests: list[CoverageRouteTestStatus]


class CoverageTestRoute(BaseModel):
    name: str
    methods: list[str]
    path: str


class CoverageTestPage(BaseModel):
    path: str


class CoverageTestDetail(BaseModel):
    nodeid: str
    routes: list[CoverageTestRoute]
    pages: list[CoverageTestPage]


class CoverageRoutesUploadResult(BaseModel):
    routes_parsed: int
    coverage: CoverageSummary
