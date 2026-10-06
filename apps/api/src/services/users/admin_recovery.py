import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from sqlmodel import select
from sqlalchemy import func
from sqlmodel.ext.asyncio.session import AsyncSession

from config.config import get_learnhouse_config
from src.db.organization_config import OrganizationConfig
from src.db.organizations import Organization
from src.db.recovery_grants import RecoveryGrant
from src.db.roles import Role, RoleTypeEnum
from src.db.user_mfa import UserMFA
from src.db.user_organizations import UserOrganization
from src.db.users import PublicUser, User
from src.security.credential_stamp import credential_is_current, password_fingerprint
from src.security.security import security_hash_password
from src.security.session_context import get_session_provenance, POLICY_AUTH_METHODS
from src.services.orgs.mfa_policy import EXTERNAL_AUTH_METHODS
from src.services.security.account_lockout import check_account_locked
from src.services.security.password_validation import validate_password_complexity
from src.services.security.rate_limiting import get_redis_connection

TTL = timedelta(minutes=15)
logger = logging.getLogger(__name__)
INVALID_LINK = "This recovery link is invalid or expired. Ask your administrator for a new link."
REDEMPTION_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 or redis.call('TTL', KEYS[1]) < 0 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""


def _limit_redemption(digest: str):
    try:
        count = int(get_redis_connection().eval(REDEMPTION_LIMIT_SCRIPT, 1, f"rate_limit:recovery_redeem:{digest}", 300))
    except Exception:
        raise HTTPException(503, "Recovery is temporarily unavailable. Please try again.") from None
    if count > 20:
        raise HTTPException(429, "Too many recovery requests. Please try again later.")


def recovery_origin() -> str:
    config = get_learnhouse_config()
    host = config.hosting_config.frontend_domain
    scheme = "https" if config.hosting_config.ssl else "http"
    value = host if "://" in host else f"{scheme}://{host}"
    parsed = urlsplit(value)
    local = parsed.hostname == "localhost"
    try:
        local = local or ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        pass
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/") or parsed.scheme not in ("http", "https")
            or (parsed.scheme != "https" and not local)):
        raise HTTPException(503, "Recovery is not configured. Contact your administrator.")
    return f"{parsed.scheme}://{parsed.netloc}"


def require_recovery_origin(request: Request) -> str:
    origin = recovery_origin()
    if request.headers.get("origin") != origin:
        raise HTTPException(403, "Recovery requests must come from the configured application.")
    return origin


async def _now(db: AsyncSession) -> datetime:
    clock = func.clock_timestamp() if db.get_bind().dialect.name == "postgresql" else func.current_timestamp()
    value = (await db.execute(select(clock))).scalar_one()
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _deny():
    raise HTTPException(403, "Only a current organization Admin can recover an eligible learner.")


def _learner_rights(role: Role) -> bool:
    if role.id != 4 or role.role_uuid != "role_global_user" or role.role_type != RoleTypeEnum.TYPE_GLOBAL or role.org_id is not None:
        return False
    rights = role.rights.model_dump() if hasattr(role.rights, "model_dump") else role.rights
    if not isinstance(rights, dict) or not rights:
        return False
    readable = {"courses", "usergroups", "folders", "media", "coursechapters", "activities", "assignments", "communities", "discussions", "podcasts", "boards", "playgrounds"}
    for resource, actions in rights.items():
        if not isinstance(actions, dict):
            return False
        for action, allowed in actions.items():
            if not isinstance(allowed, bool):
                return False
            safe = (resource in readable and action in {"action_read", "action_read_own"}) or (
                resource == "discussions" and action in {"action_create", "action_update_own", "action_delete_own"})
            if allowed and not safe:
                return False
    return rights.get("courses", {}).get("action_read") is True


def _date(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        _deny()


def _security_policy(config: OrganizationConfig) -> dict:
    try:
        security = (config.config.get("admin_toggles") or {}).get("security") or {}
        methods = security.get("allowed_auth_methods", list(POLICY_AUTH_METHODS))
        if not isinstance(methods, list) or any(m not in POLICY_AUTH_METHODS for m in methods):
            _deny()
        policy = {
            "allowed_auth_methods": sorted(set(methods)),
            "allow_central_session_sharing": security.get("allow_central_session_sharing", True),
            "require_2fa": security.get("require_2fa", False),
            "require_2fa_grace_days": security.get("require_2fa_grace_days", 0),
            "require_2fa_enabled_at": security.get("require_2fa_enabled_at"),
            "exempt_external_auth": security.get("exempt_external_auth", True),
        }
        if any(type(policy[k]) is not bool for k in ("allow_central_session_sharing", "require_2fa", "exempt_external_auth")):
            _deny()
        if type(policy["require_2fa_grace_days"]) is not int or policy["require_2fa_grace_days"] < 0:
            _deny()
        return policy
    except (AttributeError, TypeError):
        _deny()


async def _locked_authority(db: AsyncSession, issuer_id: int, target_id: int, org_id: int):
    users = (await db.execute(select(User).where(User.id.in_(sorted({issuer_id, target_id}))).order_by(User.id).with_for_update().execution_options(populate_existing=True))).scalars().all()
    by_id = {u.id: u for u in users}
    issuer, target = by_id.get(issuer_id), by_id.get(target_id)
    if issuer is None or target is None or issuer_id == target_id or target.is_superadmin or not target.password or target.signup_method not in (None, "email"):
        _deny()
    if check_account_locked(issuer)[0]:
        _deny()
    org = (await db.execute(select(Organization).where(Organization.id == org_id).with_for_update())).scalar_one_or_none()
    if org is None:
        _deny()
    memberships = (await db.execute(select(UserOrganization).where(UserOrganization.user_id.in_([issuer_id, target_id])).order_by(UserOrganization.id).with_for_update().execution_options(populate_existing=True))).scalars().all()
    mine = [m for m in memberships if m.user_id == issuer_id and m.org_id == org_id]
    theirs = [m for m in memberships if m.user_id == target_id]
    if len(mine) != 1 or mine[0].role_id != 1 or len(theirs) != 1 or theirs[0].org_id != org_id:
        _deny()
    roles = (await db.execute(select(Role).where(Role.id.in_([mine[0].role_id, theirs[0].role_id])).order_by(Role.id).with_for_update().execution_options(populate_existing=True))).scalars().all()
    learner_role = next((r for r in roles if r.id == theirs[0].role_id), None)
    if learner_role is None or not _learner_rights(learner_role):
        _deny()
    config = (await db.execute(select(OrganizationConfig).where(OrganizationConfig.org_id == org_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if config is None:
        _deny()
    policy = _security_policy(config)
    factors = (await db.execute(select(UserMFA).where(UserMFA.user_id == issuer_id).with_for_update().execution_options(populate_existing=True))).scalars().all()
    now = await _now(db)
    if policy["require_2fa"] and not any(f.confirmed_at for f in factors):
        exempt = policy["exempt_external_auth"] and (issuer.signup_method or "").lower() in EXTERNAL_AUTH_METHODS
        if not exempt:
            if policy["require_2fa_grace_days"] == 0:
                _deny()
            anchors = [_date(policy["require_2fa_enabled_at"]), _date(mine[0].creation_date)]
            anchors = [a for a in anchors if a is not None]
            if not anchors or now >= max(anchors) + timedelta(days=policy["require_2fa_grace_days"]):
                _deny()
    fingerprint = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
    return issuer, target, mine[0], theirs[0], policy, fingerprint


async def issue_recovery_link(request: Request, db: AsyncSession, actor, org_id: int, target_id: int) -> dict:
    origin = require_recovery_origin(request)
    if not isinstance(actor, PublicUser):
        _deny()
    issuer, target, mine, theirs, policy, policy_stamp = await _locked_authority(db, actor.id, target_id, org_id)
    payload = getattr(request.state, "auth_payload", None)
    if not isinstance(payload, dict) or not credential_is_current(payload, issuer):
        _deny()
    provenance = get_session_provenance()
    if provenance is None or provenance.amr not in POLICY_AUTH_METHODS:
        raise HTTPException(403, "Sign in again with an allowed sign-in method before creating a recovery link.")
    allowed = set(policy["allowed_auth_methods"])
    if allowed and not set(POLICY_AUTH_METHODS).issubset(allowed) and (provenance is None or provenance.amr not in allowed):
        _deny()
    if not policy["allow_central_session_sharing"] and (provenance is None or provenance.org_id != org_id):
        _deny()
    grant = (await db.execute(select(RecoveryGrant).where(RecoveryGrant.target_id == target_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    secret = secrets.token_urlsafe(32)
    now = await _now(db)
    fields = dict(issuer_id=issuer.id, org_id=org_id, issuer_membership_id=mine.id, target_membership_id=theirs.id,
                  secret_digest=hashlib.sha256(secret.encode()).hexdigest(), issuer_fingerprint=password_fingerprint(issuer),
                  target_fingerprint=password_fingerprint(target), policy_fingerprint=policy_stamp,
                  issued_at=now, expires_at=now + TTL)
    if grant is None:
        grant = RecoveryGrant(target_id=target_id, **fields)
    else:
        for key, value in fields.items():
            setattr(grant, key, value)
    db.add(grant)
    await db.commit()
    logger.info("Admin recovery issued issuer_id=%s target_id=%s org_id=%s", issuer.id, target.id, org_id)
    return {"link": f"{origin}/recover#token={secret}", "expires_at": fields["expires_at"].replace(tzinfo=timezone.utc).isoformat()}


async def redeem_recovery_link(db: AsyncSession, secret: str, new_password: str) -> dict:
    digest = hashlib.sha256(secret.encode()).hexdigest()
    location = (await db.execute(select(RecoveryGrant.target_id, RecoveryGrant.issuer_id, RecoveryGrant.org_id, RecoveryGrant.secret_digest, RecoveryGrant.expires_at).where(RecoveryGrant.secret_digest == digest))).first()
    if location is None or location.expires_at <= await _now(db):
        raise HTTPException(400, INVALID_LINK)
    _limit_redemption(location.secret_digest)
    validation = validate_password_complexity(new_password)
    if not validation.is_valid:
        raise HTTPException(400, {"code": "WEAK_PASSWORD", "message": "Password does not meet security requirements", "errors": validation.errors})
    new_hash = security_hash_password(new_password)
    try:
        issuer, target, mine, theirs, _, policy_stamp = await _locked_authority(db, location.issuer_id, location.target_id, location.org_id)
    except HTTPException:
        raise HTTPException(400, INVALID_LINK) from None
    grant = (await db.execute(select(RecoveryGrant).where(RecoveryGrant.target_id == target.id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    now = await _now(db)
    if (grant is None or not hmac.compare_digest(grant.secret_digest, digest) or grant.expires_at <= now
            or grant.issuer_id != issuer.id or grant.org_id != location.org_id
            or grant.issuer_membership_id != mine.id or grant.target_membership_id != theirs.id
            or not hmac.compare_digest(grant.issuer_fingerprint, password_fingerprint(issuer))
            or not hmac.compare_digest(grant.target_fingerprint, password_fingerprint(target))
            or grant.policy_fingerprint != policy_stamp):
        raise HTTPException(400, INVALID_LINK)
    target.password = new_hash
    target.password_changed_at = now
    target.failed_login_attempts = 0
    target.locked_until = None
    target.update_date = str(now)
    db.add(target)
    await db.delete(grant)
    await db.commit()
    from src.routers.users import _invalidate_session_cache
    _invalidate_session_cache(target.id)
    logger.info("Admin recovery redeemed issuer_id=%s target_id=%s org_id=%s", issuer.id, target.id, location.org_id)
    return {"message": "Password changed. Sign in with your new password."}
