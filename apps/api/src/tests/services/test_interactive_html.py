import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import select
from starlette.requests import Request

from src.db.courses.activities import ActivityCreate, ActivityLockType, ActivitySubTypeEnum, ActivityTypeEnum, ActivityUpdate
from src.db.resource_authors import ResourceAuthor, ResourceAuthorshipEnum, ResourceAuthorshipStatusEnum
from src.db.courses.interactive_html import InteractiveHtml
from src.db.users import APITokenUser
from src.services.courses.activities.activities import create_activity, get_activityby_id, update_activity
from src.services.courses.activities.interactive_html import MAX_HTML_BYTES, read_html, validate_html, write_html


@pytest.fixture
async def html_activity(db, activity):
    activity.activity_sub_type = ActivitySubTypeEnum.SUBTYPE_DYNAMIC_HTML
    activity.content = {}
    db.add(activity)
    await db.commit()
    return activity


def test_html_limit_is_utf8_bytes():
    assert MAX_HTML_BYTES == 10 * 1024 * 1024
    assert len(validate_html("é" * (MAX_HTML_BYTES // 2)).encode()) == 10 * 1024 * 1024
    with pytest.raises(HTTPException) as exc:
        validate_html("é" * (MAX_HTML_BYTES // 2) + "x")
    assert exc.value.status_code == 413


@pytest.mark.parametrize("value", [None, 1, "a\x00b", "\ud800"])
def test_rejects_invalid_html(value):
    with pytest.raises(HTTPException) as exc:
        validate_html(value)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_admin_write_and_generic_activity_never_contains_source(db, html_activity, course, admin_user, mock_request):
    source = "<script>document.body.textContent='hello'</script>"
    with patch("src.services.courses.activities.interactive_html.check_resource_access", new_callable=AsyncMock), patch(
        "src.services.courses.activities.activities.check_resource_access", new_callable=AsyncMock
    ):
        assert await write_html(mock_request, html_activity.activity_uuid, admin_user, source, db) == source
        result = await get_activityby_id(mock_request, html_activity.id, admin_user, db)
    assert result.content == {}
    assert source not in result.model_dump_json()


@pytest.mark.asyncio
async def test_learner_and_api_token_cannot_write(db, html_activity, regular_user, mock_request):
    token = APITokenUser(org_id=html_activity.org_id, created_by_user_id=regular_user.id)
    for actor in (regular_user, token):
        with pytest.raises(HTTPException) as exc:
            await write_html(mock_request, html_activity.activity_uuid, actor, "test", db)
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_actual_course_rbac_allows_admin_and_denies_learner(db, html_activity, admin_user, regular_user, mock_request):
    assert await write_html(mock_request, html_activity.activity_uuid, admin_user, "admin", db) == "admin"
    with pytest.raises(HTTPException) as exc:
        await write_html(mock_request, html_activity.activity_uuid, regular_user, "learner", db)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_anonymous_public_access_and_restricted_denial(db, html_activity, admin_user, anonymous_user, mock_request):
    await write_html(mock_request, html_activity.activity_uuid, admin_user, "public", db)
    with patch("src.services.courses.activities.activities.check_ee_activity_paid_access", new_callable=AsyncMock, return_value=True):
        assert await read_html(mock_request, html_activity.activity_uuid, anonymous_user, db) == "public"
        html_activity.lock_type = ActivityLockType.RESTRICTED
        db.add(html_activity)
        await db.commit()
        with pytest.raises(HTTPException) as exc:
            await read_html(mock_request, html_activity.activity_uuid, anonymous_user, db)
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_deleting_activity_cascades_to_private_source(db, html_activity, admin_user, mock_request):
    await db.execute(text("PRAGMA foreign_keys=ON"))
    await write_html(mock_request, html_activity.activity_uuid, admin_user, "test", db)
    activity_id = html_activity.id
    await db.delete(html_activity)
    await db.commit()
    row = (await db.execute(select(InteractiveHtml).where(InteractiveHtml.activity_id == activity_id))).scalars().first()
    assert row is None


@pytest.mark.asyncio
async def test_non_html_activity_refuses_source_access(db, activity, admin_user, mock_request):
    for operation in (read_html, write_html):
        with pytest.raises(HTTPException) as exc:
            if operation is read_html:
                await operation(mock_request, activity.activity_uuid, admin_user, db)
            else:
                await operation(mock_request, activity.activity_uuid, admin_user, "test", db)
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_maintainer_still_needs_actual_course_update_permission(db, html_activity, regular_user, mock_request):
    author = ResourceAuthor(resource_uuid="course_test", user_id=regular_user.id, authorship=ResourceAuthorshipEnum.MAINTAINER, authorship_status=ResourceAuthorshipStatusEnum.ACTIVE)
    db.add(author)
    await db.commit()
    with patch("src.services.courses.activities.interactive_html.check_resource_access", new_callable=AsyncMock, side_effect=HTTPException(status_code=403)):
        with pytest.raises(HTTPException) as exc:
            await write_html(mock_request, html_activity.activity_uuid, regular_user, "denied", db)
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_course_contributor_can_write_when_update_is_authorized(db, html_activity, regular_user, mock_request):
    author = ResourceAuthor(resource_uuid="course_test", user_id=regular_user.id, authorship=ResourceAuthorshipEnum.CONTRIBUTOR, authorship_status=ResourceAuthorshipStatusEnum.ACTIVE)
    db.add(author)
    await db.commit()
    assert await write_html(mock_request, html_activity.activity_uuid, regular_user, "test", db) == "test"


@pytest.mark.asyncio
async def test_html_source_obeys_paid_and_activity_lock(db, html_activity, course, admin_user, regular_user, mock_request):
    with patch("src.services.courses.activities.interactive_html.check_resource_access", new_callable=AsyncMock), patch(
        "src.services.courses.activities.activities.check_resource_access", new_callable=AsyncMock
    ), patch("src.services.courses.activities.activities.check_ee_activity_paid_access", new_callable=AsyncMock, return_value=True) as paid:
        await write_html(mock_request, html_activity.activity_uuid, admin_user, "test", db)
        assert await read_html(mock_request, html_activity.activity_uuid, regular_user, db) == "test"
        paid.return_value = False
        with pytest.raises(HTTPException) as exc:
            await read_html(mock_request, html_activity.activity_uuid, regular_user, db)
        assert exc.value.status_code == 403
        paid.return_value = True
        html_activity.lock_type = ActivityLockType.RESTRICTED
        db.add(html_activity)
        await db.commit()
        with pytest.raises(HTTPException) as exc:
            await read_html(mock_request, html_activity.activity_uuid, regular_user, db)
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_draft_is_editor_only_and_empty_is_safe(db, html_activity, admin_user, regular_user, mock_request):
    html_activity.published = False
    db.add(html_activity)
    await db.commit()
    with patch("src.services.courses.activities.activities.check_resource_access", new_callable=AsyncMock), patch(
        "src.services.courses.activities.activities.check_ee_activity_paid_access", new_callable=AsyncMock, return_value=True
    ):
        assert await read_html(mock_request, html_activity.activity_uuid, admin_user, db) == ""
        with pytest.raises(HTTPException) as exc:
            await read_html(mock_request, html_activity.activity_uuid, regular_user, db)
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_unpublished_course_and_parent_chapter_restrictions(db, html_activity, course, chapter, admin_user, regular_user, mock_request):
    with patch("src.services.courses.activities.activities.check_resource_access", new_callable=AsyncMock), patch(
        "src.services.courses.activities.activities.check_ee_activity_paid_access", new_callable=AsyncMock, return_value=True
    ):
        await write_html(mock_request, html_activity.activity_uuid, admin_user, "secret", db)
        course.published = False
        db.add(course)
        await db.commit()
        with pytest.raises(HTTPException) as exc:
            await read_html(mock_request, html_activity.activity_uuid, regular_user, db)
        assert exc.value.status_code == 403
        course.published = True
        chapter.lock_type = ActivityLockType.RESTRICTED
        db.add(course)
        db.add(chapter)
        await db.commit()
        with pytest.raises(HTTPException) as exc:
            await read_html(mock_request, html_activity.activity_uuid, regular_user, db)
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_generic_create_and_update_reject_html_source(db, org, course, chapter, html_activity, admin_user, mock_request):
    payload = ActivityCreate(name="HTML", chapter_id=chapter.id, activity_type=ActivityTypeEnum.TYPE_DYNAMIC, activity_sub_type=ActivitySubTypeEnum.SUBTYPE_DYNAMIC_HTML, content={"html": "<script>1</script>"})
    with patch("src.services.courses.activities.interactive_html.check_resource_access", new_callable=AsyncMock), patch(
        "src.services.courses.activities.activities.check_resource_access", new_callable=AsyncMock
    ):
        with pytest.raises(HTTPException) as create_exc:
            await create_activity(mock_request, payload, admin_user, db)
        assert create_exc.value.status_code == 422
        with pytest.raises(HTTPException) as update_exc:
            await update_activity(mock_request, ActivityUpdate(content={"html": "<script>1</script>"}), html_activity.activity_uuid, admin_user, db)
        assert update_exc.value.status_code == 422


@pytest.mark.asyncio
async def test_existing_activity_cannot_be_converted_to_html(db, activity, admin_user, mock_request):
    with patch("src.services.courses.activities.interactive_html.check_resource_access", new_callable=AsyncMock), patch(
        "src.services.courses.activities.activities.check_resource_access", new_callable=AsyncMock
    ):
        with pytest.raises(HTTPException) as exc:
            await update_activity(mock_request, ActivityUpdate(activity_sub_type=ActivitySubTypeEnum.SUBTYPE_DYNAMIC_HTML, content={}), activity.activity_uuid, admin_user, db)
        assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_http_json_contract_and_no_cache(db, html_activity, admin_user):
    from src.routers.courses.activities.activities import api_read_interactive_html, api_write_interactive_html

    data = json.dumps({"html": "<script>2+2</script>"}).encode()
    async def receive():
        return {"type": "http.request", "body": data, "more_body": False}
    scope = {"type": "http", "method": "PUT", "path": "/", "headers": [], "query_string": b""}
    request = Request(scope, receive)
    with patch("src.services.courses.activities.interactive_html.check_resource_access", new_callable=AsyncMock), patch(
        "src.services.courses.activities.activities.check_resource_access", new_callable=AsyncMock
    ), patch("src.services.courses.activities.activities.check_ee_activity_paid_access", new_callable=AsyncMock, return_value=True):
        saved = await api_write_interactive_html(request, html_activity.activity_uuid, admin_user, db)
        assert json.loads(saved.body) == {"html": "<script>2+2</script>"}
        assert saved.headers["cache-control"] == "no-store"
        assert saved.headers["x-content-type-options"] == "nosniff"
        loaded = await api_read_interactive_html(request, html_activity.activity_uuid, admin_user, db)
        assert json.loads(loaded.body) == {"html": "<script>2+2</script>"}
        assert loaded.headers["cache-control"] == "no-store"
        assert loaded.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_http_upload_accepts_10_mib_and_rejects_one_byte_more(db, html_activity, admin_user):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from src.core.events.database import get_db_session
    from src.routers.courses.activities.activities import router
    from src.security.auth import get_current_user

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: admin_user

    content = "x" * (10 * 1024 * 1024)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        path = f"/{html_activity.activity_uuid}/interactive-html"
        saved = await client.put(path, json={"html": content})
        assert saved.status_code == 200
        assert saved.json() == {"html": content}
        rejected = await client.put(path, json={"html": content + "x"})
        assert rejected.status_code == 413


@pytest.mark.asyncio
async def test_clone_refuses_html_before_side_effects(db, course, html_activity, admin_user, mock_request):
    from src.db.courses.courses import Course
    from src.services.courses.courses import clone_course

    with patch("src.services.courses.courses.check_resource_access", new_callable=AsyncMock), patch(
        "src.services.courses.courses.check_limits_with_usage", new_callable=AsyncMock
    ) as usage:
        with pytest.raises(HTTPException) as exc:
            await clone_course(mock_request, course.course_uuid, admin_user, db)
        assert exc.value.status_code == 409
        usage.assert_not_awaited()
    assert len((await db.execute(select(Course))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_export_refuses_html_before_creating_archive(db, course, html_activity, admin_user, mock_request):
    from src.services.courses.transfer.export_service import export_courses_batch

    with patch("src.services.courses.transfer.export_service.check_resource_access", new_callable=AsyncMock), patch(
        "src.services.courses.transfer.export_service._build_export_zip"
    ) as build:
        with pytest.raises(HTTPException) as exc:
            await export_courses_batch(mock_request, [course.course_uuid], admin_user, db)
        assert exc.value.status_code == 409
        build.assert_not_called()


@pytest.mark.asyncio
async def test_clone_rechecks_rows_when_preflight_was_stale(db, course, html_activity, admin_user, mock_request):
    from src.db.courses.courses import Course
    from src.services.courses.courses import clone_course

    # Model an HTML activity becoming visible after the preflight SELECT.
    with patch("src.services.courses.activities.interactive_html.reject_html_transfer", new_callable=AsyncMock), patch(
        "src.services.courses.courses.check_resource_access", new_callable=AsyncMock
    ), patch("src.services.courses.courses.check_limits_with_usage", new_callable=AsyncMock) as usage, patch(
        "os.makedirs"
    ) as mkdir:
        with pytest.raises(HTTPException) as exc:
            await clone_course(mock_request, course.course_uuid, admin_user, db)
        assert exc.value.status_code == 409
        usage.assert_not_awaited()
        mkdir.assert_not_called()
    assert len((await db.execute(select(Course))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_export_rechecks_rows_when_preflight_was_stale(db, course, html_activity, admin_user, mock_request):
    from src.services.courses.transfer.export_service import export_courses_batch

    with patch("src.services.courses.transfer.export_service.reject_html_transfer", new_callable=AsyncMock), patch(
        "src.services.courses.transfer.export_service.check_resource_access", new_callable=AsyncMock
    ), patch("src.services.courses.transfer.export_service._build_export_zip") as build:
        with pytest.raises(HTTPException) as exc:
            await export_courses_batch(mock_request, [course.course_uuid], admin_user, db)
        assert exc.value.status_code == 409
        build.assert_not_called()


@pytest.mark.asyncio
async def test_import_refuses_html_before_claim_or_course_write(db, org, admin_user, mock_request, tmp_path, monkeypatch):
    from src.db.courses.courses import Course
    from src.services.courses.transfer import import_service
    from src.services.courses.transfer.models import ImportOptions

    temp = tmp_path / "test-package"
    extracted = temp / "extracted"
    activity_dir = extracted / "courses" / "test" / "chapters" / "ch" / "activities" / "act"
    activity_dir.mkdir(parents=True)
    (extracted / "manifest.json").write_text(json.dumps({"courses": [{"course_uuid": "original", "path": "courses/test"}]}))
    (activity_dir / "activity.json").write_text(json.dumps({"activity_sub_type": "SUBTYPE_DYNAMIC_HTML"}))
    monkeypatch.setattr(import_service, "TEMP_IMPORT_DIR", str(tmp_path))
    with patch("src.services.courses.transfer.import_service.check_resource_access", new_callable=AsyncMock):
        with pytest.raises(HTTPException) as exc:
            await import_service.import_courses(mock_request, "test-package", org.id, ImportOptions(course_uuids=["original"]), admin_user, db)
        assert exc.value.status_code == 409
    assert temp.exists()
    assert not (tmp_path / "test-package-importing").exists()
    assert (await db.execute(select(Course))).scalars().all() == []


@pytest.mark.asyncio
async def test_html_version_restore_fails_instead_of_silently_restoring_no_source(db, html_activity, admin_user, mock_request):
    from src.services.courses.activities.versioning import restore_activity_version

    with patch("src.services.courses.activities.versioning.check_feature_access", new_callable=AsyncMock), patch(
        "src.services.courses.activities.versioning.check_resource_access", new_callable=AsyncMock
    ):
        with pytest.raises(HTTPException) as exc:
            await restore_activity_version(mock_request, html_activity.activity_uuid, 1, admin_user, db)
        assert exc.value.status_code == 409
