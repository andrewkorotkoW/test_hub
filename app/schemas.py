from typing import Literal, Optional

from pydantic import BaseModel, Field

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
    repeat: int = Field(default=1, ge=1, le=20)


class ShareLinkCreate(BaseModel):
    expires: Literal["7d", "30d", "never"] = "30d"


class ShareLink(BaseModel):
    token: str
    url: str
    created_by: str
    created_at: str
    expires_at: Optional[str] = None
    revoked: bool


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
    kind: Literal["route", "page"] = "route"


class CoverageMapArea(BaseModel):
    area: str
    routes: list[CoverageMapRoute]


class CoverageSummary(BaseModel):
    project: str
    generated_at: str
    stands: list[CoverageStandSummary]
    routes_total: int
    routes_covered: int
    pages_total: int
    pages_covered: int
    zero_coverage_areas: list[str]
    map: list[CoverageMapArea]
    test_status: dict[str, dict[str, int]]


class CoverageRouteTestStatus(BaseModel):
    nodeid: str
    env: Optional[str] = None
    status: dict[str, Optional[str]]


class CoverageRouteDetail(BaseModel):
    name: str
    methods: list[str]
    path: str
    tests: list[CoverageRouteTestStatus]


class CoveragePageDetail(BaseModel):
    path: str
    tests: list[CoverageRouteTestStatus]


class CoverageGraphNode(BaseModel):
    id: str
    kind: Literal["route", "page", "test"]
    label: str
    ref: str  # nodeid (test) / route name (route) / path (page) без префикса id
    path: Optional[str] = None
    methods: list[str] = []
    tests_count: int = 0


class CoverageGraphEdge(BaseModel):
    source: str
    target: str


class CoverageGraph(BaseModel):
    scope: str
    nodes: list[CoverageGraphNode]
    edges: list[CoverageGraphEdge]
    truncated: bool
    node_count: int


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


class CoverageTree(BaseModel):
    tree: dict[str, dict[str, list[str]]]
    error: Optional[str] = None
    stands: list[str]
    run_ids: dict[str, Optional[int]]
    statuses: dict[str, dict[str, str]]  # stand -> nodeid -> status


class FlakyTestStat(BaseModel):
    project: str
    stand: str
    test: str
    nodeid: Optional[str] = None
    runs: int
    fails: int
    flips: int
    score: float
    last_statuses: list[str]
    updated_at: Optional[str] = None


class FlakyTestList(BaseModel):
    items: list[FlakyTestStat]


class FlakyTestHistoryEntry(BaseModel):
    run_id: int
    status: str


class FlakyTestHistory(BaseModel):
    test: str
    stand: str
    history: list[FlakyTestHistoryEntry]
