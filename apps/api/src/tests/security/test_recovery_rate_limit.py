import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.services.users.admin_recovery import _limit_redemption


def test_redemption_budget_is_atomic_and_expires_in_real_redis(monkeypatch):
    url = os.environ.get("RECOVERY_TEST_REDIS_URL")
    if not url:
        pytest.skip("Set RECOVERY_TEST_REDIS_URL for the real Redis limiter test")
    parsed = urlsplit(url)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.scheme not in {"redis", "rediss"}:
        pytest.fail("Recovery limiter test requires a loopback Redis URL")
    from redis import Redis
    client = Redis.from_url(url)
    digest = hashlib.sha256(uuid4().bytes).hexdigest()
    key = f"rate_limit:recovery_redeem:{digest}"
    monkeypatch.setattr("src.services.users.admin_recovery.get_redis_connection", lambda: client)
    def attempt(_):
        try:
            _limit_redemption(digest)
            return 200
        except HTTPException as exc:
            return exc.status_code
    try:
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(attempt, range(30)))
        assert results.count(200) == 20
        assert results.count(429) == 10
        assert 0 < client.ttl(key) <= 300
    finally:
        client.delete(key)
        client.close()
