import logging
import runpy
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient

from config import config as config_module
from src.core.events.database import get_db_session
from src.routers import recovery as recovery_routes
from src.security.recovery_privacy import recovery_request


ORIGIN = "https://school.test"
REDEEM = "/api/v1/users/recovery-links/redeem"
SECRET = "PrivateRecoveryCredentialNeverExported12345"
PASSWORD = "PrivatePasswordNeverExported!123"


@pytest.fixture
def privacy_app(db, monkeypatch):
    app = FastAPI()
    app.include_router(recovery_routes.router, prefix="/api/v1/users/recovery-links")
    app.dependency_overrides[get_db_session] = lambda: db
    cfg = SimpleNamespace(hosting_config=SimpleNamespace(frontend_domain="school.test", ssl=True))
    monkeypatch.setattr("src.services.users.admin_recovery.get_learnhouse_config", lambda: cfg)
    monkeypatch.setattr(recovery_routes, "check_rate_limit", lambda *args: (True, 1, 300))

    @app.get("/ordinary")
    async def ordinary():
        return {"recovery_context": recovery_request.get()}

    return app


async def test_secret_bearing_failure_is_generic_and_request_context_is_reset(privacy_app, monkeypatch):
    observed = []

    async def fail(db, secret, new_password):
        observed.append(recovery_request.get())
        raise RuntimeError(f"Injected database failure with {secret} and {new_password}")

    monkeypatch.setattr(recovery_routes, "redeem_recovery_link", fail)
    async with AsyncClient(transport=ASGITransport(app=privacy_app), base_url=ORIGIN) as client:
        result = await client.post(REDEEM, headers={"Origin": ORIGIN}, json={
            "secret": SECRET, "new_password": PASSWORD,
        })
        assert result.status_code == 503
        assert result.json() == {"detail": "Recovery is temporarily unavailable. Please try again."}
        assert result.headers["cache-control"] == "no-store"
        assert result.headers["referrer-policy"] == "no-referrer"
        assert observed == [True]
        assert SECRET not in result.text and PASSWORD not in result.text
        assert (await client.get("/ordinary")).json() == {"recovery_context": False}
    assert recovery_request.get() is False


@pytest.mark.parametrize("body", [
    {"secret": {"credential": SECRET}, "new_password": PASSWORD},
    {"secret": SECRET, "new_password": {"password": PASSWORD}},
    {"secret": SECRET, "new_password": PASSWORD, "unexpected": SECRET},
])
async def test_validation_errors_never_echo_secret_inputs(privacy_app, body):
    async with AsyncClient(transport=ASGITransport(app=privacy_app), base_url=ORIGIN) as client:
        result = await client.post(REDEEM, headers={"Origin": ORIGIN}, json=body)
    assert result.status_code == 400
    assert result.json() == {"detail": "Invalid recovery request."}
    assert SECRET not in result.text and PASSWORD not in result.text
    assert result.headers["cache-control"] == "no-store"


@pytest.fixture
def sentry_runtime(monkeypatch):
    sdk = pytest.importorskip("sentry_sdk")
    from sentry_sdk.transport import Transport

    class MemoryTransport(Transport):
        def __init__(self):
            super().__init__()
            self.envelopes = []

        def capture_envelope(self, envelope):
            self.envelopes.append(envelope)

    config = config_module.get_learnhouse_config().model_copy(deep=True)
    config.general_config.sentry_config.dsn = "http://public@127.0.0.1/1"
    options = {}

    def capture_configuration(**kwargs):
        options.update(kwargs)

    async def unused_lifespan():
        pass

    events = ModuleType("src.core.events.events")
    events.startup_app = lambda app: unused_lifespan
    events.shutdown_app = lambda app: unused_lifespan
    router = ModuleType("src.router")
    router.v1_router = APIRouter()
    modules = {events.__name__: events, router.__name__: router}
    for name in ("src.routers.content_files", "src.routers.local_content"):
        module = ModuleType(name)
        module.router = APIRouter()
        modules[name] = module

    with patch.dict(sys.modules, modules), patch.object(config_module, "get_learnhouse_config", return_value=config), patch.object(sdk, "init", capture_configuration):
        runpy.run_path(str(Path(__file__).resolve().parents[3] / "app.py"), run_name="recovery_telemetry_configuration")

    transport = MemoryTransport()
    options.update(transport=transport, traces_sample_rate=1.0, profile_session_sample_rate=0.0)
    client = sdk.Client(**options)
    with sdk.isolation_scope() as scope:
        scope.set_client(client)
        try:
            yield SimpleNamespace(sdk=sdk, client=client, transport=transport)
        finally:
            client.close(timeout=2)


async def test_sentry_drops_recovery_errors_logs_and_traces_but_keeps_normal_events(privacy_app, sentry_runtime, monkeypatch):
    from sentry_sdk.integrations.asgi import SentryAsgiMiddleware

    r = sentry_runtime

    async def fail(db, secret, new_password):
        try:
            raise RuntimeError(f"Injected {secret} {new_password}")
        except RuntimeError:
            r.sdk.capture_exception()
            logging.getLogger("recovery.telemetry.test").error("Injected %s %s", secret, new_password)
            r.sdk.logger.error("Injected recovery log", attributes={"secret": secret, "password": new_password})
            raise

    monkeypatch.setattr(recovery_routes, "redeem_recovery_link", fail)
    app = SentryAsgiMiddleware(privacy_app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        result = await client.post(REDEEM, headers={"Origin": ORIGIN}, json={
            "secret": SECRET, "new_password": PASSWORD,
        })
        assert result.status_code == 503
        assert (await client.get("/ordinary")).status_code == 200
    r.sdk.capture_message("ordinary-event-retained")
    r.sdk.logger.info("ordinary-log-retained")
    r.client.flush(timeout=2)
    payload = b"\n".join(envelope.serialize() for envelope in r.transport.envelopes).decode()
    assert "ordinary-event-retained" in payload
    assert "ordinary-log-retained" in payload
    assert SECRET not in payload and PASSWORD not in payload
    transaction_urls = [
        event["request"]["url"]
        for envelope in r.transport.envelopes
        if (event := envelope.get_transaction_event()) is not None
    ]
    assert transaction_urls == [ORIGIN + "/ordinary"]


def test_sentry_url_filter_protects_events_after_recovery_context_has_ended(sentry_runtime):
    r = sentry_runtime
    assert recovery_request.get() is False
    r.sdk.capture_event({
        "message": "Injected secret-bearing late event",
        "request": {"url": ORIGIN + REDEEM, "data": {"secret": SECRET, "new_password": PASSWORD}},
        "extra": {"secret": SECRET},
    })
    r.sdk.capture_message("late-control-retained")
    r.client.flush(timeout=2)
    payload = b"\n".join(envelope.serialize() for envelope in r.transport.envelopes).decode()
    assert "late-control-retained" in payload
    assert "Injected secret-bearing late event" not in payload
    assert SECRET not in payload and PASSWORD not in payload
