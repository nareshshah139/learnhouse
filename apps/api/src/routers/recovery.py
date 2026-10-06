import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.security.auth import get_authenticated_user
from src.security.recovery_privacy import recovery_request
from src.services.security.rate_limiting import check_rate_limit
from src.services.users.admin_recovery import issue_recovery_link, redeem_recovery_link, require_recovery_origin

PRIVATE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


class RecoveryRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            context = recovery_request.set(True)
            try:
                response = await original(request)
            except HTTPException as exc:
                response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
            except Exception:
                response = JSONResponse({"detail": "Recovery is temporarily unavailable. Please try again."}, status_code=503)
            finally:
                recovery_request.reset(context)
            response.headers.update(PRIVATE_HEADERS)
            return response

        return handle


router = APIRouter(route_class=RecoveryRoute)


async def _body(request: Request, keys: set[str]) -> dict:
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(400, "Send a JSON recovery request.")
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > 4096):
        raise HTTPException(400, "Invalid recovery request.")
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 4096:
            raise HTTPException(400, "Invalid recovery request.")
        raw.extend(chunk)
    try:
        body = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "Invalid recovery request.") from None
    if not isinstance(body, dict) or set(body) != keys:
        raise HTTPException(400, "Invalid recovery request.")
    return body


def _limit(key: str, count: int):
    try:
        allowed, _, _ = check_rate_limit(key, count, 300)
    except Exception:
        raise HTTPException(503, "Recovery is temporarily unavailable. Please try again.") from None
    if not allowed:
        raise HTTPException(429, "Too many recovery requests. Please try again later.")


@router.post("/issue")
async def issue(request: Request, actor=Depends(get_authenticated_user), db: AsyncSession = Depends(get_db_session)):
    try:
        require_recovery_origin(request)
        body = await _body(request, {"org_id", "target_id"})
        if any(type(body[k]) is not int or body[k] <= 0 for k in body):
            raise HTTPException(400, "Invalid recovery request.")
        _limit(f"recovery_issue:{actor.id}", 10)
        _limit(f"recovery_target:{actor.id}:{body['target_id']}", 5)
        return await issue_recovery_link(request, db, actor, body["org_id"], body["target_id"])
    except Exception:
        await db.rollback()
        raise


@router.post("/redeem")
async def redeem(request: Request, db: AsyncSession = Depends(get_db_session)):
    try:
        require_recovery_origin(request)
        body = await _body(request, {"secret", "new_password"})
        if (not isinstance(body["secret"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", body["secret"])
                or not isinstance(body["new_password"], str) or not 1 <= len(body["new_password"]) <= 1024):
            raise HTTPException(400, "Invalid recovery request.")
        return await redeem_recovery_link(db, body["secret"], body["new_password"])
    except Exception:
        await db.rollback()
        raise
