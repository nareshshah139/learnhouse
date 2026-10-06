from contextvars import ContextVar

recovery_request = ContextVar("recovery_request", default=False)


def is_recovery_event(event: dict) -> bool:
    url = (event.get("request") or {}).get("url", "")
    transaction = event.get("transaction", "")
    return recovery_request.get() or any("/recovery-links/" in value for value in (url, transaction) if isinstance(value, str))
