"""REST API поверх app/core/test_cases.py — тест-кейсы проекта (импорт
markdown-черновиков auto_tests_vshgu, ручное заведение, дерево по разделам с
фильтрами, правка, скриншоты шагов). Права — как у app/routers/xfail.py: qa
правит (включая ручную загрузку/удаление вложений), manager/customer только
читают. Автозагрузка allure-скриншотов (source='allure') — не через API, см.
app.core.test_cases.sync_run_attachments, вызывается раннером."""
import sqlite3

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response

from ..config import settings
from ..core import test_cases
from ..deps import get_db, require_roles
from ..schemas import TestCase, TestCaseAttachment, TestCaseCreate, TestCaseImportResult, TestCaseTree, TestCaseUpdate

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


@router.post("/{name}/testcases/{case_id}/steps/{step_n}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_testcase_attachment(
    name: str,
    case_id: int,
    step_n: int,
    file: UploadFile = File(...),
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> TestCaseAttachment:
    _get_project_or_404(conn, name)
    raw = await file.read()
    if len(raw) > settings.TH_TESTCASE_ATTACHMENT_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Attachment exceeds TH_TESTCASE_ATTACHMENT_MAX_BYTES ({settings.TH_TESTCASE_ATTACHMENT_MAX_BYTES} bytes)",
        )
    try:
        attachment = test_cases.add_manual_attachment(conn, name, case_id, step_n, file.filename or "", raw)
    except test_cases.UnsupportedAttachmentType:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported file type (PNG/JPG only)"
        )
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case not found")
    return TestCaseAttachment(**attachment)


@router.delete("/{name}/testcases/{case_id}/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_testcase_attachment(
    name: str,
    case_id: int,
    attachment_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa")),
) -> Response:
    _get_project_or_404(conn, name)
    try:
        deleted = test_cases.delete_manual_attachment(conn, name, case_id, attachment_id)
    except test_cases.NotManualAttachment:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Allure attachments are managed automatically"
        )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{name}/testcases/{case_id}/attachments/{attachment_id}")
async def get_testcase_attachment(
    name: str,
    case_id: int,
    attachment_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(require_roles("qa", "manager", "customer")),
) -> Response:
    _get_project_or_404(conn, name)
    result = test_cases.get_attachment_file(conn, name, case_id, attachment_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    content, mime = result
    return Response(content=content, media_type=mime)
