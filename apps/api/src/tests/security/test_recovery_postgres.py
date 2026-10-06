"""Opt in with RECOVERY_TEST_POSTGRES_URL pointing only at a loopback test DB."""

import asyncio
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.organization_config import OrganizationConfig
from src.db.organizations import Organization
from src.db.recovery_grants import RecoveryGrant
from src.db.roles import Role
from src.db.user_mfa import UserMFA
from src.db.user_organizations import UserOrganization
from src.db.users import PublicUser, User, UserUpdatePassword
from src.routers.recovery import router
from src.security.auth import create_access_token
from src.security.credential_stamp import password_fingerprint
from src.security.security import security_hash_password, security_verify_password
from src.services.users.users import update_user_password


@pytest.fixture
async def pg_recovery():
    url = os.environ.get("RECOVERY_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set RECOVERY_TEST_POSTGRES_URL for real PostgreSQL recovery races")
    parsed = urlsplit(url)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.scheme != "postgresql+asyncpg":
        pytest.fail("Recovery concurrency tests require a loopback PostgreSQL URL")
    schema = "recovery_test_" + uuid4().hex
    control = create_async_engine(url)
    async with control.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    tables = [m.__table__ for m in (User, Organization, Role, UserOrganization, OrganizationConfig, UserMFA, RecoveryGrant)]
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda connection: SQLModel.metadata.create_all(connection, tables=tables))
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            org = Organization(id=1, name="Synthetic School", email="school@example.com", slug="synthetic", org_uuid="org_recovery_test", creation_date="", update_date="")
            admin = User(id=1, username="admin", first_name="Synthetic", last_name="Admin", email="recovery-admin@example.com", password=security_hash_password("AdminOriginal!123"), user_uuid="user_recovery_admin")
            learner = User(id=2, username="learner", first_name="Synthetic", last_name="Learner", email="recovery-learner@example.com", password=security_hash_password("LearnerOriginal!123"), signup_method="email", user_uuid="user_recovery_learner")
            db.add_all([org, admin, learner])
            await db.commit()
            db.add_all([Role(id=1, name="Admin", role_uuid="role_global_admin", rights={}), Role(id=4, name="User", role_uuid="role_global_user", rights={"courses": {"action_read": True}})])
            await db.commit()
            db.add_all([UserOrganization(id=1, user_id=1, org_id=1, role_id=1, creation_date="2026-01-01", update_date=""), UserOrganization(id=2, user_id=2, org_id=1, role_id=4, creation_date="2026-01-01", update_date=""), OrganizationConfig(org_id=1, config={})])
            await db.commit()
            token = create_access_token({"sub": admin.email, "pwdv": password_fingerprint(admin), "amr": "password", "sorg": 1})
        async def session():
            async with factory() as db:
                yield db
        app = FastAPI()
        app.include_router(router, prefix="/recovery")
        app.dependency_overrides[get_db_session] = session
        cfg = SimpleNamespace(hosting_config=SimpleNamespace(frontend_domain="school.test", ssl=True))
        with patch("src.services.users.admin_recovery.get_learnhouse_config", return_value=cfg), patch("src.routers.recovery.check_rate_limit", return_value=(True, 1, 300)), patch("src.security.auth._is_token_revoked_for_user", return_value=False), patch("src.routers.users._invalidate_session_cache"), patch("src.services.users.admin_recovery._limit_redemption"):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="https://school.test", headers={"Origin": "https://school.test"}) as client:
                async def issue():
                    response = await client.post("/recovery/issue", json={"org_id": 1, "target_id": 2}, headers={"Authorization": f"Bearer {token}"})
                    assert response.status_code == 200, response.text
                    return response.json()["link"].split("#token=")[1]
                async def redeem(secret, password="RecoveredLearner!123"):
                    return await client.post("/recovery/redeem", json={"secret": secret, "new_password": password})
                yield SimpleNamespace(factory=factory, issue=issue, redeem=redeem)
    finally:
        await engine.dispose()
        async with control.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await control.dispose()


async def test_two_simultaneous_consumers_change_password_once(pg_recovery):
    r = pg_recovery
    secret = await r.issue()
    results = await asyncio.gather(r.redeem(secret, "FirstWinner!123"), r.redeem(secret, "SecondWinner!123"))
    assert sorted(response.status_code for response in results) == [200, 400]
    winner = "FirstWinner!123" if results[0].status_code == 200 else "SecondWinner!123"
    async with r.factory() as db:
        user = await db.get(User, 2)
        assert security_verify_password(winner, user.password)
        assert await db.get(RecoveryGrant, 2) is None


async def test_simultaneous_replacement_leaves_only_one_usable_link(pg_recovery):
    r = pg_recovery
    first, second = await asyncio.gather(r.issue(), r.issue())
    responses = await asyncio.gather(r.redeem(first), r.redeem(second))
    assert sorted(response.status_code for response in responses) == [200, 400]


async def test_expiry_uses_wall_clock_after_waiting_for_user_lock(pg_recovery):
    r = pg_recovery
    secret = await r.issue()
    async with r.factory() as db:
        grant = await db.get(RecoveryGrant, 2)
        grant.expires_at = datetime.utcnow() + timedelta(seconds=1)
        await db.commit()
        await db.execute(select(User).where(User.id == 2).with_for_update())
        waiting = asyncio.create_task(r.redeem(secret))
        await asyncio.sleep(1.2)
        await db.rollback()
    response = await waiting
    assert response.status_code == 400
    async with r.factory() as db:
        assert security_verify_password("LearnerOriginal!123", (await db.get(User, 2)).password)


async def test_stale_self_password_change_cannot_overwrite_recovery(pg_recovery):
    r = pg_recovery
    secret = await r.issue()
    async with r.factory() as stale:
        user = await stale.get(User, 2)
        actor = PublicUser(**user.model_dump())
        assert (await r.redeem(secret)).status_code == 200
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await update_user_password(None, stale, actor, 2, UserUpdatePassword(old_password="LearnerOriginal!123", new_password="StaleOverwrite!123"))
        assert exc.value.status_code == 401
        await stale.rollback()
    async with r.factory() as db:
        assert security_verify_password("RecoveredLearner!123", (await db.get(User, 2)).password)


@pytest.mark.parametrize("change", ["issuer_demoted", "issuer_locked", "target_promoted", "second_membership"])
async def test_authority_change_committed_while_redeem_waits_is_observed(pg_recovery, change):
    r = pg_recovery
    secret = await r.issue()
    from src.services.users.admin_recovery import _locked_authority
    entered = asyncio.Event()
    async def waiting_authority(*args):
        entered.set()
        return await _locked_authority(*args)
    async with r.factory() as changing:
        if change == "second_membership":
            changing.add(Organization(id=2, name="Other School", email="other@example.com", slug="other", org_uuid="org_other", creation_date="", update_date=""))
            await changing.commit()
        user_id = 1 if change.startswith("issuer") else 2
        user = (await changing.execute(select(User).where(User.id == user_id).with_for_update())).scalar_one()
        with patch("src.services.users.admin_recovery._locked_authority", side_effect=waiting_authority):
            pending = asyncio.create_task(r.redeem(secret))
            await asyncio.wait_for(entered.wait(), 3)
            if change == "issuer_locked":
                user.locked_until = "2099-01-01"
            elif change == "second_membership":
                changing.add(UserOrganization(id=3, user_id=2, org_id=2, role_id=4, creation_date="", update_date=""))
            else:
                membership = await changing.get(UserOrganization, user_id)
                membership.role_id = 4 if change == "issuer_demoted" else 1
            await changing.commit()
            assert (await pending).status_code == 400
    async with r.factory() as db:
        assert security_verify_password("LearnerOriginal!123", (await db.get(User, 2)).password)
        assert await db.get(RecoveryGrant, 2) is not None
