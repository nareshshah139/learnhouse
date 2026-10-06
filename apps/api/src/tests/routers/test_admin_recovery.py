from datetime import datetime, timedelta, timezone
import hashlib
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from src.core.events.database import get_db_session
from src.db.organization_config import OrganizationConfig
from src.db.recovery_grants import RecoveryGrant
from src.db.roles import RoleTypeEnum
from src.db.user_organizations import UserOrganization
from src.db.users import APITokenUser, User
from src.db.user_mfa import UserMFA, UserMFABackupCode
from src.routers.recovery import router
from src.security.auth import create_access_token
from src.security.credential_stamp import CREDENTIAL_CLAIM, password_fingerprint
from src.security.security import security_hash_password, security_verify_password
from src.services.admin.admin import issue_user_token
from src.services.users.admin_recovery import _limit_redemption

ORIGIN = "https://school.test"
ISSUE = "/api/v1/users/recovery-links/issue"
REDEEM = "/api/v1/users/recovery-links/redeem"
PASSWORD = "LearnerChooses!123"


@pytest.fixture
async def recovery(db, org, admin_user, regular_user, user_role):
    user_role.org_id = None
    user_role.role_type = RoleTypeEnum.TYPE_GLOBAL
    user_role.role_uuid = "role_global_user"
    user_role.rights = {"courses": {"action_read": True}, "dashboard": {"action_access": False},
                        "discussions": {"action_create": True, "action_read": True, "action_update_own": True, "action_delete_own": True}}
    admin = await db.get(User, admin_user.id)
    target = await db.get(User, regular_user.id)
    admin.password = security_hash_password("Administrator!123")
    target.password = security_hash_password("OriginalLearner!123")
    target.signup_method = "email"
    target.failed_login_attempts = 4
    target.locked_until = "2099-01-01T00:00:00"
    config = OrganizationConfig(org_id=org.id, config={}, creation_date="", update_date="")
    db.add(config)
    await db.commit()
    token = create_access_token({"sub": admin.email, "pwdv": password_fingerprint(admin), "amr": "password", "sorg": org.id})
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/users/recovery-links")
    app.dependency_overrides[get_db_session] = lambda: db
    config_mock = SimpleNamespace(hosting_config=SimpleNamespace(frontend_domain="school.test", ssl=True))
    with patch("src.services.users.admin_recovery.get_learnhouse_config", return_value=config_mock), patch(
        "src.routers.recovery.check_rate_limit", return_value=(True, 1, 300)
    ), patch("src.security.auth._is_token_revoked_for_user", return_value=False), patch("src.routers.users._invalidate_session_cache"), patch("src.services.users.admin_recovery._limit_redemption"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
            yield SimpleNamespace(client=client, admin=admin, target=target, role=user_role, org=org, config=config,
                                  token=token, body={"org_id": org.id, "target_id": target.id}, db=db)


async def issue(r, **kwargs):
    return await r.client.post(ISSUE, json=kwargs.get("body", r.body), headers={"Authorization": f"Bearer {r.token}"})


def secret(response):
    return response.json()["link"].split("#token=")[1]


async def redeem(r, value, password=PASSWORD):
    return await r.client.post(REDEEM, json={"secret": value, "new_password": password}, cookies={"LH_token": "stale"})


async def test_issue_and_redeem_have_only_credential_effects(recovery):
    r = recovery
    old_hash = r.target.password
    memberships = [(m.id, m.user_id, m.role_id, m.org_id) for m in (await r.db.execute(select(UserOrganization))).scalars()]
    response = await issue(r)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.json()["link"].startswith(ORIGIN + "/recover#token=")
    grant = await r.db.get(RecoveryGrant, r.target.id)
    assert len(secret(response)) == 43
    assert secret(response) not in str(grant.model_dump())
    assert grant.expires_at - grant.issued_at == timedelta(minutes=15)
    await r.db.refresh(r.target)
    assert (r.target.password, r.target.failed_login_attempts, r.target.locked_until) == (old_hash, 4, "2099-01-01T00:00:00")
    assert r.target.password_changed_at is None
    verified = r.target.email_verified
    changed = await redeem(r, secret(response))
    assert changed.status_code == 200, changed.text
    assert "set-cookie" not in changed.headers
    assert set(changed.json()) == {"message"}
    await r.db.refresh(r.target)
    assert security_verify_password(PASSWORD, r.target.password)
    assert r.target.password_changed_at is not None
    assert r.target.failed_login_attempts == 0 and r.target.locked_until is None
    assert r.target.email_verified == verified
    assert await r.db.get(RecoveryGrant, r.target.id) is None
    assert [(m.id, m.user_id, m.role_id, m.org_id) for m in (await r.db.execute(select(UserOrganization))).scalars()] == memberships
    assert (await redeem(r, secret(response))).status_code == 400


async def test_reissue_weak_password_and_get_do_not_consume(recovery):
    r = recovery
    first, second = await issue(r), await issue(r)
    assert first.status_code == second.status_code == 200
    assert (await r.client.get(REDEEM)).status_code == 405
    assert (await redeem(r, secret(first))).status_code == 400
    weak = await redeem(r, secret(second), "weak")
    assert weak.status_code == 400
    assert weak.json()["detail"]["code"] == "WEAK_PASSWORD"
    assert (await redeem(r, secret(second))).status_code == 200


@pytest.mark.parametrize("change", ["superadmin", "custom_role", "authoring_right", "other_org", "issuer_demoted", "issuer_locked", "target_password", "issuer_password", "membership_identity", "policy"])
async def test_redeem_rechecks_authority(recovery, change):
    r = recovery
    response = await issue(r)
    assert response.status_code == 200, response.text
    old_hash = r.target.password
    if change == "superadmin":
        r.target.is_superadmin = True
    elif change == "custom_role":
        r.role.role_uuid = "custom_learner"
    elif change == "authoring_right":
        rights = dict(r.role.rights)
        rights["courses"] = {**rights["courses"], "action_create": True}
        r.role.rights = rights
    elif change == "other_org":
        r.db.add(UserOrganization(user_id=r.target.id, org_id=999, role_id=4, creation_date="", update_date=""))
    elif change in ("issuer_demoted", "membership_identity"):
        membership = (await r.db.execute(select(UserOrganization).where(UserOrganization.user_id == (r.admin.id if change == "issuer_demoted" else r.target.id)))).scalars().first()
        if change == "issuer_demoted":
            membership.role_id = 2
        else:
            await r.db.delete(membership)
            await r.db.flush()
            r.db.add(UserOrganization(id=999, user_id=r.target.id, org_id=r.org.id, role_id=4, creation_date="", update_date=""))
    elif change == "issuer_locked":
        r.admin.locked_until = "2099-01-01T00:00:00"
    elif change == "target_password":
        r.target.password = security_hash_password("DifferentLearner!123")
        old_hash = r.target.password
    elif change == "issuer_password":
        r.admin.password = security_hash_password("DifferentAdmin!123")
    elif change == "policy":
        r.config.config = {"admin_toggles": {"security": {"allow_central_session_sharing": False}}}
    await r.db.commit()
    result = await redeem(r, secret(response))
    assert result.status_code == 400
    target = await r.db.get(User, r.body["target_id"])
    assert target.password == old_hash


@pytest.mark.parametrize("actor", ["anonymous", "learner", "maintainer", "superadmin_without_membership", "api_token"])
async def test_issue_denies_non_admin_sessions(recovery, actor):
    r = recovery
    if actor == "anonymous":
        result = await r.client.post(ISSUE, json=r.body)
    elif actor == "api_token":
        result = await r.client.post(ISSUE, json=r.body, headers={"Authorization": "Bearer lh_not-a-real-token"})
    else:
        membership = (await r.db.execute(select(UserOrganization).where(UserOrganization.user_id == r.admin.id))).scalars().one()
        if actor == "superadmin_without_membership":
            r.admin.is_superadmin = True
            await r.db.delete(membership)
        else:
            membership.role_id = 4 if actor == "learner" else 2
        await r.db.commit()
        result = await issue(r)
    assert result.status_code in (401, 403)
    assert result.headers["cache-control"] == "no-store"
    assert (await r.db.execute(select(RecoveryGrant))).scalars().all() == []


async def test_expiry_and_commit_failure_leave_password_unchanged(recovery):
    r = recovery
    response = await issue(r)
    old_hash, target_id = r.target.password, r.target.id
    with patch.object(r.db, "commit", side_effect=RuntimeError("injected database failure")):
        failed = await redeem(r, secret(response))
    assert failed.status_code == 503
    target = await r.db.get(User, target_id)
    assert target.password == old_hash
    grant = await r.db.get(RecoveryGrant, target_id)
    assert grant is not None
    grant.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    await r.db.commit()
    assert (await redeem(r, secret(response))).status_code == 400


async def test_origin_validation_and_limiter_fail_closed(recovery):
    r = recovery
    bad = await r.client.post(ISSUE, json=r.body, headers={"Origin": "https://attacker.test", "Authorization": f"Bearer {r.token}"})
    assert bad.status_code == 403
    with patch("src.routers.recovery.check_rate_limit", side_effect=ConnectionError("offline")):
        assert (await issue(r)).status_code == 503
    with patch("src.routers.recovery.check_rate_limit", return_value=(False, 10, 300)):
        assert (await issue(r)).status_code == 429
    malformed = await r.client.post(REDEEM, json={"secret": {"sensitive": "never-echo"}, "new_password": "never-echo"})
    assert malformed.status_code == 400
    assert "never-echo" not in malformed.text


@pytest.mark.parametrize("method", [None, "unknown", "api_token"])
async def test_issue_requires_known_human_session(recovery, method):
    r = recovery
    r.token = create_access_token({"sub": r.admin.email, "pwdv": password_fingerprint(r.admin), "amr": method})
    assert (await issue(r)).status_code == 403
    assert (await r.db.execute(select(RecoveryGrant))).scalars().all() == []


async def test_api_impersonation_token_cannot_create_recovery_link(recovery):
    r = recovery
    machine = APITokenUser(org_id=r.org.id, created_by_user_id=r.admin.id)
    result = await issue_user_token(machine, r.admin.id, r.db)
    r.token = result["access_token"]
    response = await issue(r)
    assert response.status_code == 403
    assert "Sign in again" in response.json()["detail"]


async def test_oversized_chunked_body_is_rejected_before_reading_rest(recovery):
    r = recovery
    async def chunks():
        yield b'{"secret":"' + b'A' * 4080
        yield b'A' * 20
        raise AssertionError("The parser must stop at the size limit")
    response = await r.client.post(REDEEM, content=chunks(), headers={"Content-Type": "application/json"})
    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"
    assert "AAAA" not in response.text


async def test_recovery_never_changes_mfa_or_backup_codes(recovery):
    r = recovery
    factor = UserMFA(user_id=r.target.id, secret_encrypted="synthetic-not-a-real-secret", confirmed_at="2026-01-01")
    backup = UserMFABackupCode(user_id=r.target.id, code_hash="synthetic-hash", creation_date="2026-01-01")
    r.db.add_all([factor, backup])
    await r.db.commit()
    before = (factor.model_dump(), backup.model_dump())
    response = await issue(r)
    assert response.status_code == 200
    assert (factor.model_dump(), backup.model_dump()) == before
    assert (await redeem(r, secret(response))).status_code == 200
    await r.db.refresh(factor)
    await r.db.refresh(backup)
    assert (factor.model_dump(), backup.model_dump()) == before


async def test_issuer_mfa_grace_expiry_is_rechecked_without_session_context(recovery):
    r = recovery
    anchor = datetime.now(timezone.utc)
    r.config.config = {"admin_toggles": {"security": {"require_2fa": True, "require_2fa_grace_days": 1, "require_2fa_enabled_at": anchor.isoformat()}}}
    membership = (await r.db.execute(select(UserOrganization).where(UserOrganization.user_id == r.admin.id))).scalar_one()
    membership.creation_date = "2020-01-01"
    await r.db.commit()
    response = await issue(r)
    assert response.status_code == 200
    grant = await r.db.get(RecoveryGrant, r.target.id)
    grant.expires_at = (anchor + timedelta(days=2)).replace(tzinfo=None)
    await r.db.commit()
    with patch("src.services.users.admin_recovery._now", return_value=(anchor + timedelta(days=1, seconds=1)).replace(tzinfo=None)):
        assert (await redeem(r, secret(response))).status_code == 400


@pytest.mark.parametrize("policy", [
    {"allowed_auth_methods": ["google"]},
    {"allow_central_session_sharing": False},
    {"require_2fa": True, "require_2fa_grace_days": 0, "require_2fa_enabled_at": "2020-01-01"},
])
async def test_issuer_must_satisfy_current_org_session_policies(recovery, policy):
    r = recovery
    r.config.config = {"admin_toggles": {"security": policy}}
    r.token = create_access_token({"sub": r.admin.email, "pwdv": password_fingerprint(r.admin), "amr": "password"})
    await r.db.commit()
    assert (await issue(r)).status_code == 403


async def test_redeem_rate_limit_isolated_per_hashed_capability_not_proxy_ip(recovery):
    r = recovery
    counts = {}
    def eval_script(script, number, key, window):
        counts[key] = counts.get(key, 0) + 1
        return counts[key]
    target_b = User(id=22, username="synthetic_b", first_name="Second", last_name="Learner", email="recovery-b@example.com", password=security_hash_password("OriginalSecond!123"), signup_method="email", user_uuid="user_recovery_b")
    r.db.add(target_b)
    await r.db.commit()
    r.db.add(UserOrganization(user_id=22, org_id=r.org.id, role_id=4, creation_date="2020-01-01", update_date=""))
    await r.db.commit()
    first = secret(await issue(r))
    other = secret(await issue(r, body={"org_id": r.org.id, "target_id": 22}))
    with patch("src.services.users.admin_recovery._limit_redemption", side_effect=_limit_redemption), patch("src.services.users.admin_recovery.get_redis_connection", return_value=SimpleNamespace(eval=eval_script)):
        for _ in range(20):
            assert (await redeem(r, first, "weak")).status_code == 400
        assert (await redeem(r, first, "weak")).status_code == 429
        second_response = await redeem(r, other, "weak")
        assert second_response.status_code == 400 and second_response.json()["detail"]["code"] == "WEAK_PASSWORD"
        replacement = secret(await issue(r))
        fresh = await redeem(r, replacement, "weak")
        assert fresh.status_code == 400 and fresh.json()["detail"]["code"] == "WEAK_PASSWORD"
    assert set(counts) == {"rate_limit:recovery_redeem:" + hashlib.sha256(value.encode()).hexdigest() for value in (first, other, replacement)}
    assert first not in str(counts) and other not in str(counts)


async def test_unknown_or_expired_grants_do_not_allocate_limiter_keys_or_hash_passwords(recovery):
    r = recovery
    response = await issue(r)
    grant = await r.db.get(RecoveryGrant, r.target.id)
    grant.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    await r.db.commit()
    with patch("src.services.users.admin_recovery._limit_redemption") as limit, patch("src.services.users.admin_recovery.security_hash_password") as hash_password:
        for value in ("A" * 43, secret(response)):
            failed = await redeem(r, value, "weak")
            assert failed.status_code == 400
            assert isinstance(failed.json()["detail"], str)
        limit.assert_not_called()
        hash_password.assert_not_called()


async def test_redemption_redis_outage_blocks_before_hashing_and_preserves_grant(recovery):
    r = recovery
    response = await issue(r)
    target_id, old_hash = r.target.id, r.target.password
    unavailable = Mock()
    unavailable.eval.side_effect = ConnectionError("offline")
    with patch("src.services.users.admin_recovery._limit_redemption", side_effect=_limit_redemption), patch("src.services.users.admin_recovery.get_redis_connection", return_value=unavailable), patch("src.services.users.admin_recovery.security_hash_password") as hash_password:
        assert (await redeem(r, secret(response))).status_code == 503
        hash_password.assert_not_called()
    assert (await r.db.get(User, target_id)).password == old_hash
    assert await r.db.get(RecoveryGrant, target_id) is not None


async def test_audit_messages_contain_only_safe_identifiers(recovery, caplog):
    r = recovery
    caplog.set_level("INFO", logger="src.services.users.admin_recovery")
    response = await issue(r)
    value = secret(response)
    assert (await redeem(r, value)).status_code == 200
    assert "Admin recovery issued issuer_id=" in caplog.text
    assert "Admin recovery redeemed issuer_id=" in caplog.text
    assert value not in caplog.text
    assert hashlib.sha256(value.encode()).hexdigest() not in caplog.text
    assert PASSWORD not in caplog.text
    assert r.target.email not in caplog.text
