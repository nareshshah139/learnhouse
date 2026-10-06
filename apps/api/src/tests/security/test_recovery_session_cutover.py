import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import jwt
import pyotp
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from src.core.events.database import get_db_session
from src.db.user_mfa import UserMFA, UserMFABackupCode
from src.db.users import User
from src.routers import auth as auth_routes
from src.routers import mfa as mfa_routes
from src.security import auth
from src.security.security import security_verify_password
from src.services.auth.mfa import encrypt_secret
from src.tests.security.test_recovery_postgres import pg_recovery as pg_recovery


OLD_PASSWORD = "LearnerOriginal!123"
NEW_PASSWORD = "RecoveredLearner!123"
LEARNER_EMAIL = "recovery-learner@example.com"


@pytest.fixture
async def cutover(pg_recovery, monkeypatch):
    r = pg_recovery
    async with r.factory.kw["bind"].begin() as connection:
        await connection.run_sync(
            lambda sync: UserMFABackupCode.__table__.create(sync, checkfirst=True)
        )
    async with r.factory() as db:
        learner = await db.get(User, 2)
        learner.email_verified = True
        await db.commit()

    async def session():
        async with r.factory() as db:
            yield db

    app = FastAPI()
    app.include_router(auth_routes.router, prefix="/auth")
    app.include_router(mfa_routes.router, prefix="/auth")
    app.dependency_overrides[get_db_session] = session

    @app.get("/whoami")
    async def whoami(user=Depends(auth.get_authenticated_user)):
        return {"id": user.id, "email": user.email}

    monkeypatch.setattr(auth_routes, "check_login_rate_limit", lambda request: (True, 0))
    monkeypatch.setattr(auth_routes, "check_refresh_rate_limit", lambda request: (True, 0))
    monkeypatch.setattr(auth_routes, "record_audit_event", AsyncMock())
    monkeypatch.setattr(mfa_routes, "_check_mfa_rate_limit", lambda *args: None)
    monkeypatch.setattr(auth, "_get_revocation_redis_client", lambda: None)
    monkeypatch.setattr(auth, "_record_activity_from_request", lambda *args: None)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="https://school.test",
    ) as client:
        yield SimpleNamespace(client=client, recovery=r, factory=r.factory)


async def login(r, password=OLD_PASSWORD):
    return await r.client.post(
        "/auth/login", data={"username": LEARNER_EMAIL, "password": password}
    )


async def access(r, token):
    return await r.client.get("/whoami", headers={"Authorization": f"Bearer {token}"})


async def refresh(r, token):
    return await r.client.get(
        "/auth/refresh", headers={"Cookie": f"{auth.JWT_REFRESH_COOKIE_NAME}={token}"}
    )


async def recover(r):
    secret = await r.recovery.issue()
    response = await r.recovery.redeem(secret, NEW_PASSWORD)
    assert response.status_code == 200, response.text
    async with r.factory() as db:
        learner = await db.get(User, 2)
        assert security_verify_password(NEW_PASSWORD, learner.password)
        return learner.password_changed_at


async def assert_tokens_rejected(r, tokens):
    assert (await access(r, tokens["access_token"])).status_code == 401
    assert (await refresh(r, tokens["refresh_token"])).status_code == 401


async def enroll_mfa(r):
    secret = pyotp.random_base32()
    async with r.factory() as db:
        db.add(UserMFA(
            user_id=2,
            secret_encrypted=encrypt_secret(secret),
            confirmed_at=datetime.now(timezone.utc).isoformat(),
        ))
        await db.commit()
    return secret


async def complete_mfa(r, pending_token, secret):
    return await r.client.post("/auth/login/mfa", json={
        "mfa_token": pending_token,
        "code": pyotp.TOTP(secret).now(),
    })


async def test_recovery_revokes_real_access_and_refresh_without_redis(cutover):
    r = cutover
    initial = await login(r)
    assert initial.status_code == 200, initial.text
    old = initial.json()["tokens"]
    assert (await access(r, old["access_token"])).json() == {
        "id": 2, "email": LEARNER_EMAIL,
    }
    rotated = await refresh(r, old["refresh_token"])
    assert rotated.status_code == 200, rotated.text
    await recover(r)
    await assert_tokens_rejected(r, old)
    await assert_tokens_rejected(r, rotated.json())
    fresh = await login(r, NEW_PASSWORD)
    assert fresh.status_code == 200, fresh.text
    fresh_tokens = fresh.json()["tokens"]
    assert (await access(r, fresh_tokens["access_token"])).status_code == 200
    assert (await refresh(r, fresh_tokens["refresh_token"])).status_code == 200


async def test_new_login_in_the_reset_second_is_usable(cutover, monkeypatch):
    r = cutover
    changed_at = await recover(r)
    frozen = changed_at.replace(tzinfo=timezone.utc)

    class TokenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen if tz is not None else frozen.replace(tzinfo=None)

    monkeypatch.setattr(auth, "datetime", TokenClock)
    response = await login(r, NEW_PASSWORD)
    assert response.status_code == 200, response.text
    tokens = response.json()["tokens"]
    assert auth.decode_jwt(tokens["access_token"])["iat"] == int(frozen.timestamp())
    assert (await access(r, tokens["access_token"])).status_code == 200
    assert (await refresh(r, tokens["refresh_token"])).status_code == 200


@pytest.mark.parametrize("iat", ["missing", None, True, "invalid", [], {}, 0, float("nan"), float("inf")])
async def test_legacy_missing_or_malformed_iat_cannot_cross_recovery(cutover, iat):
    r = cutover
    await recover(r)
    claims = {"sub": LEARNER_EMAIL, "exp": datetime.now(timezone.utc) + timedelta(minutes=10)}
    if iat != "missing":
        claims["iat"] = iat
    access_token = jwt.encode(claims, auth.SECRET_KEY, algorithm=auth.ALGORITHM)
    refresh_token = jwt.encode({**claims, "type": "refresh"}, auth.SECRET_KEY, algorithm=auth.ALGORITHM)
    access_result = await access(r, access_token)
    refresh_result = await refresh(r, refresh_token)
    assert (access_result.status_code, refresh_result.status_code) == (401, 401)


async def test_refresh_snapshot_before_reset_cannot_mint_usable_tokens(cutover, monkeypatch):
    r = cutover
    initial = await login(r)
    assert initial.status_code == 200, initial.text
    reached, release = asyncio.Event(), asyncio.Event()
    original = auth_routes.security_get_user

    async def paused_lookup(*args, **kwargs):
        snapshot = await original(*args, **kwargs)
        reached.set()
        await release.wait()
        return snapshot

    monkeypatch.setattr(auth_routes, "security_get_user", paused_lookup)
    waiting = asyncio.create_task(refresh(r, initial.json()["tokens"]["refresh_token"]))
    try:
        await asyncio.wait_for(reached.wait(), 5)
        await recover(r)
    finally:
        release.set()
        response = await asyncio.wait_for(waiting, 5)
    monkeypatch.setattr(auth_routes, "security_get_user", original)
    if response.status_code != 401:
        assert response.status_code == 200, response.text
        await assert_tokens_rejected(r, response.json())


async def test_old_password_login_paused_before_mint_is_revoked(cutover, monkeypatch):
    r = cutover
    reached, release = asyncio.Event(), asyncio.Event()
    original = auth_routes.issue_session_or_challenge

    async def paused_issue(*args, **kwargs):
        reached.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(auth_routes, "issue_session_or_challenge", paused_issue)
    waiting = asyncio.create_task(login(r))
    try:
        await asyncio.wait_for(reached.wait(), 5)
        await recover(r)
    finally:
        release.set()
        response = await asyncio.wait_for(waiting, 5)
    monkeypatch.setattr(auth_routes, "issue_session_or_challenge", original)
    if response.status_code != 401:
        assert response.status_code == 200, response.text
        await assert_tokens_rejected(r, response.json()["tokens"])


async def test_recovery_revokes_pending_mfa_but_preserves_the_factor(cutover):
    r = cutover
    secret = await enroll_mfa(r)
    pending = await login(r)
    assert pending.status_code == 200, pending.text
    assert pending.json()["mfa_required"] is True
    await recover(r)
    stale = await complete_mfa(r, pending.json()["mfa_token"], secret)
    assert stale.status_code == 401
    assert stale.json()["detail"]["code"] == "MFA_SESSION_EXPIRED"
    fresh = await login(r, NEW_PASSWORD)
    assert fresh.json()["mfa_required"] is True
    completed = await complete_mfa(r, fresh.json()["mfa_token"], secret)
    assert completed.status_code == 200, completed.text
    assert (await access(r, completed.json()["tokens"]["access_token"])).status_code == 200


async def test_mfa_completion_paused_after_cutover_check_cannot_restore_session(cutover, monkeypatch):
    r = cutover
    secret = await enroll_mfa(r)
    pending = await login(r)
    assert pending.status_code == 200, pending.text
    reached, release = asyncio.Event(), asyncio.Event()
    original = mfa_routes.get_user_mfa

    async def paused_factor(*args, **kwargs):
        factor = await original(*args, **kwargs)
        reached.set()
        await release.wait()
        return factor

    monkeypatch.setattr(mfa_routes, "get_user_mfa", paused_factor)
    waiting = asyncio.create_task(complete_mfa(r, pending.json()["mfa_token"], secret))
    try:
        await asyncio.wait_for(reached.wait(), 5)
        await recover(r)
    finally:
        release.set()
        response = await asyncio.wait_for(waiting, 5)
    monkeypatch.setattr(mfa_routes, "get_user_mfa", original)
    if response.status_code != 401:
        assert response.status_code == 200, response.text
        await assert_tokens_rejected(r, response.json()["tokens"])
