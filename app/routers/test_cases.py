"""REST API поверх app/core/test_cases.py — тест-кейсы проекта (импорт
markdown-черновиков auto_tests_vshgu, ручное заведение, дерево по разделам с
фильтрами, правка). Права — как у app/routers/xfail.py: qa правит, manager/
customer только читают."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..core import test_cases
from ..deps import get_db, require_roles
from ..schemas import TestCase, TestCaseCreate, TestCaseImportResult, TestCaseTree, TestCaseUpdate

router = APIRouter(prefix="/api/projects", tags=["testcases"])


def _get_project_or_404(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row


@router.post("/{name}/testcases/import", status_code=status.HTTP_201_CREATED)
async def import_testcases(
    name: str,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> TestCaseImportResult:
    project = _get_project_or_404(conn, name)
    result = test_cases.import_drafts(conn, project)
    return TestCaseImportResult(**result)


@router.post("/{name}/testcases", status_code=status.HTTP_201_CREATED)
async def create_testcase(
    name: str,
    body: TestCaseCreate,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_roles("qa")),
) -> TestCase:
    _get_project_or_404(conn, name)
    case = test_cases.create_manual(
        conn, name, body.section, body.title, body.precondition, body.priority,
        [s.model_dump() for s in body.steps], body.nodeid, user["login"],
    )
    return TestCase(**case)


@router.get("/{name}/testcases")
async def list_testcases(
    name: str,
    section: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    has_test: bool | None = None,
    q: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa", "manager", "customer")),
) -> TestCaseTree:
    _get_project_or_404(conn, name)
    tree = test_cases.list_tree(conn, name, section=section, status=status_filter, has_test=has_test, q=q)
    return TestCaseTree(**tree)


@router.get("/{name}/testcases/{case_id}")
async def get_testcase(
    name: str,
    case_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa", "manager", "customer")),
) -> TestCase:
    _get_project_or_404(conn, name)
    case = test_cases.get_case(conn, name, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case not found")
    return TestCase(**case)


@router.put("/{name}/testcases/{case_id}")
async def update_testcase(
    name: str,
    case_id: int,
    body: TestCaseUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_roles("qa")),
) -> TestCase:
    _get_project_or_404(conn, name)
    existing = test_cases.get_case(conn, name, case_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case not found")
    case = test_cases.update_case(
        conn, case_id, body.title, body.precondition, body.priority,
        [s.model_dump() for s in body.steps], body.nodeid, user["login"],
    )
    return TestCase(**case)
