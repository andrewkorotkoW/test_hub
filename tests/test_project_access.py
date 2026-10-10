"""Доступ к GET /api/projects по ролям (уточнение к миссии профилей пользователей):

- customer с заполненным users.project — жёстко один этот проект.
- customer/любой пользователь с users.project IS NULL — видит все проекты.
  Это намеренный fallback (не частный случай по login): иначе сервисная
  учётка tg-бота (роль 'customer', users.project всегда NULL) потеряла бы
  обзор всех проектов и сломалась бы вся её боевая функциональность
  (app/tg_bot.py) — а исключать её по логину явно запрещено (ревью отклонило
  такой bypass). Побочный эффект: обычный ещё не привязанный к проекту
  customer тоже временно видит все проекты, пока ему не назначат project.
- manager — несколько проектов через таблицу-связку user_projects (фильтр по
  роли, а не по project IS NULL): тот, что выбрал при регистрации
  (переносится из users.project при одобрении заявки ролью manager), плюс
  любые, что создаст сам (POST /api/projects теперь разрешён и manager'у).
- qa/superadmin — без изменений, видят всё.
"""

from app.config import settings

from .conftest import login, register_project


async def _project_names(client) -> set[str]:
    resp = await client.get("/api/projects")
    assert resp.status_code == 200
    return {p["name"] for p in resp.json()}


async def test_customer_without_project_sees_all_projects(customer_client):
    # project IS NULL -> fallback "видит всё" (не частный случай, см. docstring).
    # Сиды (bike_fit/Velo_bot/VSHGU/Demo) гарантируют непустой список проектов.
    assert "bike_fit" in await _project_names(customer_client)


async def test_customer_sees_only_own_project(client, tmp_path):
    # qa_client/customer_client — ОДИН и тот же AsyncClient (общая cookie jar,
    # см. conftest.py), поэтому для одновременной работы под двумя ролями нужен
    # явный login() между шагами, а не два ролевых фикстура сразу в сигнатуре.
    resp = await login(client, "qa", "qa")
    assert resp.status_code == 200
    await register_project(client, "cust_proj_a", tmp_path)
    await register_project(client, "cust_proj_b", tmp_path)

    resp = await login(client, "customer", "customer")
    assert resp.status_code == 200
    resp = await client.put("/api/me", json={"project": "cust_proj_a"})
    assert resp.status_code == 200

    assert await _project_names(client) == {"cust_proj_a"}


async def test_manager_without_membership_sees_empty_list(manager_client):
    assert await _project_names(manager_client) == set()


async def test_manager_can_create_project_and_gets_access(manager_client, tmp_path):
    resp = await manager_client.post(
        "/api/projects",
        json={"name": "mgr_proj_1", "path": str(tmp_path), "venv": ".venv"},
    )
    assert resp.status_code == 201
    assert await _project_names(manager_client) == {"mgr_proj_1"}

    # второй созданный проект добавляется, а не заменяет первый — через
    # user_projects, не через одиночное поле users.project.
    resp = await manager_client.post(
        "/api/projects",
        json={"name": "mgr_proj_2", "path": str(tmp_path), "venv": ".venv"},
    )
    assert resp.status_code == 201
    assert await _project_names(manager_client) == {"mgr_proj_1", "mgr_proj_2"}


async def test_qa_create_project_does_not_grant_user_projects_row(client, tmp_path):
    # qa создаёт проект, и этот проект не должен попасть manager'у в user_projects
    # просто потому, что qa — не manager (у qa и так полный доступ через роль).
    resp = await login(client, "qa", "qa")
    assert resp.status_code == 200
    await register_project(client, "qa_proj", tmp_path)

    resp = await login(client, "manager", "manager")
    assert resp.status_code == 200
    assert await _project_names(client) == set()


async def test_approve_as_manager_transfers_registration_project(client, qa_client, tmp_path):
    await register_project(qa_client, "reg_proj", tmp_path)

    resp = await client.post(
        "/api/auth/register",
        json={
            "login": "new_manager",
            "password": "pw12345",
            "full_name": "New Manager",
            "position": "QA lead",
            "project": "reg_proj",
        },
    )
    assert resp.status_code == 201

    # заявка ещё не одобрена — войти нельзя.
    resp = await login(client, "new_manager", "pw12345")
    assert resp.status_code == 403

    resp = await qa_client.put("/api/users/new_manager/approve", json={"role": "manager"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "manager"

    resp = await login(client, "new_manager", "pw12345")
    assert resp.status_code == 200

    assert await _project_names(client) == {"reg_proj"}


async def test_approve_as_customer_does_not_populate_user_projects(client, qa_client, tmp_path):
    await register_project(qa_client, "stay_single_proj", tmp_path)

    resp = await client.post(
        "/api/auth/register",
        json={
            "login": "new_customer_approved",
            "password": "pw12345",
            "full_name": "New Customer",
            "position": "Client",
            "project": "stay_single_proj",
        },
    )
    assert resp.status_code == 201

    resp = await qa_client.put("/api/users/new_customer_approved/approve", json={"role": "customer"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "customer"

    resp = await login(client, "new_customer_approved", "pw12345")
    assert resp.status_code == 200

    # всё ещё единственный источник для customer — users.project, не таблица-связка.
    assert await _project_names(client) == {"stay_single_proj"}


async def test_customer_forbidden_on_project_create(customer_client, tmp_path):
    resp = await customer_client.post(
        "/api/projects",
        json={"name": "forbidden_by_customer", "path": str(tmp_path), "venv": ".venv"},
    )
    assert resp.status_code == 403


async def test_tg_bot_service_account_still_sees_all_projects(client, qa_client, tmp_path):
    # Регрессия на конфликт, найденный при анализе кода: сервисная учётка бота
    # (app/db.py::_seed_tg_bot_user) заведена с ролью 'customer' и project=NULL
    # исключительно ради отсутствия CRUD, а не ради ограничения её одним
    # проектом — бот должен сохранить обзор всех проектов.
    await register_project(qa_client, "bot_visible_proj", tmp_path)

    all_names = await _project_names(qa_client)
    assert "bot_visible_proj" in all_names

    resp = await login(client, settings.TH_TG_SERVICE_LOGIN, settings.TH_TG_SERVICE_PASSWORD)
    assert resp.status_code == 200
    assert resp.json()["role"] == "customer"

    assert await _project_names(client) == all_names
