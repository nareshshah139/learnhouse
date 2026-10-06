import hashlib
import hmac
import math
from datetime import datetime, timezone

from config.config import get_learnhouse_config

CREDENTIAL_CLAIM = "pwdv"


def password_fingerprint(user) -> str:
    key = get_learnhouse_config().security_config.auth_jwt_secret_key
    value = f"learnhouse:credential:v1:{user.id}:{getattr(user, 'password', '')}"
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


def token_issued_at(payload: dict):
    value = payload.get("iat")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def credential_is_current(payload: dict, user) -> bool:
    stamp = payload.get(CREDENTIAL_CLAIM)
    if stamp is not None:
        return isinstance(stamp, str) and stamp.isascii() and len(stamp) == 64 and hmac.compare_digest(stamp, password_fingerprint(user))
    cutoff = getattr(user, "password_changed_at", None)
    if not isinstance(cutoff, datetime):
        return True
    issued = token_issued_at(payload)
    cutoff = cutoff.replace(tzinfo=timezone.utc) if cutoff.tzinfo is None else cutoff
    return issued is not None and issued >= cutoff


def carried_credential_stamp(payload: dict, user) -> str:
    return payload.get(CREDENTIAL_CLAIM) or password_fingerprint(user)
