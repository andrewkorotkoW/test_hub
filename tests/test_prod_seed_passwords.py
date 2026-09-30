"""TH_ENV=prod: seed-пользователи не должны получать статичные пароли 'qa'/'admin'/...
без дополнительного действия (задача t2 из docs/missions/2026-09-30_server_readiness.md).
Прочитан app/db.py::_seed_if_empty/_seed_superadmin/_log_generated_passwords: реализация
генерирует случайный secrets.token_urlsafe(12) для каждого seed-пользователя (SEED_USERS
+ SUPERADMIN) и логирует пароли один раз через logger.warning - без принудительной смены
пароля при первом входе (в коде это явно объяснено как компромисс, не требующий новой
колонки/экрана). Тесты ниже пишут в свою tmp-БД (settings.DB_PATH), не трогая боевую."""
import sqlite3

from app.config import settings
from app.db import SUPERADMIN_LOGIN, init_db
from app.security import verify_password


def _init_db_with_env(tmp_path, monkeypatch, th_env):
    monkeypatch.setattr(settings, "TH_ENV", th_env)
    monkeypatch.setattr(settings, "DB_PATH", tmp_path / "test_hub.db")
    init_db()
    return tmp_path / "test_hub.db"


def _password_hashes(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return {r["login"]: r["password_hash"] for r in conn.execute("SELECT login, password_hash FROM users").fetchall()}
    finally:
        conn.close()


def test_prod_seed_users_reject_the_dev_default_passwords(tmp_path, monkeypatch, caplog):
    with caplog.at_level("WARNING"):
        db_path = _init_db_with_env(tmp_path, monkeypatch, "prod")

    hashes = _password_hashes(db_path)
    assert set(hashes) == {"qa", "manager", "customer", "admin", "tg_bot"}
    for login_, dev_default_password in (
        ("qa", "qa"), ("manager", "manager"), ("customer", "customer"), (SUPERADMIN_LOGIN, "admin"),
    ):
        assert not verify_password(dev_default_password, hashes[login_]), (
            f"{login_}: статичный dev-пароль всё ещё подходит в TH_ENV=prod"
        )

    assert "сгенерированы случайные пароли" in caplog.text
    for login_ in ("qa", "manager", "customer", SUPERADMIN_LOGIN):
        assert login_ in caplog.text


def test_dev_seed_users_keep_known_default_passwords(tmp_path, monkeypatch):
    # Регрессия: TH_ENV=dev (поведение владельца по умолчанию) не должен затрагиваться
    # новой prod-веткой - известные пароли из README/памяти по-прежнему работают.
    db_path = _init_db_with_env(tmp_path, monkeypatch, "dev")

    hashes = _password_hashes(db_path)
    for login_, dev_default_password in (
        ("qa", "qa"), ("manager", "manager"), ("customer", "customer"), (SUPERADMIN_LOGIN, "admin"),
    ):
        assert verify_password(dev_default_password, hashes[login_])


def test_prod_seed_passwords_are_stable_across_restarts(tmp_path, monkeypatch):
    # init_db() вызывается при каждом рестарте systemd-сервиса (см. deploy/test_hub.service)
    # - повторный вызов не должен перегенерировать/сбрасывать уже выданные пароли.
    db_path = _init_db_with_env(tmp_path, monkeypatch, "prod")
    before = _password_hashes(db_path)

    init_db()

    after = _password_hashes(db_path)
    assert before == after


def test_prod_seed_tg_bot_user_still_uses_static_configured_password(tmp_path, monkeypatch):
    """ДЕФЕКТ (не правлю, только фиксирую тестом): _seed_tg_bot_user (app/db.py) не
    проверяет settings.TH_ENV вообще - в отличие от SEED_USERS/_seed_superadmin,
    сервисная учётка Telegram-бота всегда получает пароль settings.TH_TG_SERVICE_PASSWORD
    (по умолчанию буквально 'tg_bot') без генерации случайного пароля и без записи в лог,
    даже в TH_ENV=prod. Если оператор не переопределит TH_TG_SERVICE_PASSWORD сам, эта
    учётка (роль customer: видит проекты/стенды/дерево, запускает прогоны) в проде
    остаётся с предсказуемым паролем из репозитория/README."""
    db_path = _init_db_with_env(tmp_path, monkeypatch, "prod")

    hashes = _password_hashes(db_path)
    assert verify_password(settings.TH_TG_SERVICE_PASSWORD, hashes[settings.TH_TG_SERVICE_LOGIN])
