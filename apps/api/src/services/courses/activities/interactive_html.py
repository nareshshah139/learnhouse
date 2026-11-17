from datetime import datetime

from fastapi import HTTPException, Request
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.activities import Activity, ActivitySubTypeEnum, ActivityTypeEnum
from src.db.courses.courses import Course
from src.db.courses.interactive_html import InteractiveHtml
from src.db.users import PublicUser
from src.security.rbac import AccessAction, check_resource_access

MAX_HTML_BYTES = 10 * 1024 * 1024


def validate_html(html: object) -> str:
    if not isinstance(html, str) or "\x00" in html:
        raise HTTPException(status_code=422, detail="HTML must be UTF-8 text without NUL characters")
    try:
        size = len(html.encode("utf-8", errors="strict"))
    except UnicodeEncodeError:
        raise HTTPException(status_code=422, detail="HTML must be valid UTF-8")
    if size > MAX_HTML_BYTES:
        raise HTTPException(status_code=413, detail="HTML exceeds the 10 MiB limit")
    return html


async def require_html_editor(request: Request, course: Course, user: object, db: AsyncSession) -> None:
    if not isinstance(user, PublicUser) or not user.id:
        raise HTTPException(status_code=403, detail="An instructor session is required")
    await check_resource_access(request, db, user, course.course_uuid, AccessAction.UPDATE)


def require_html_activity(activity: Activity) -> None:
    if activity.activity_type != ActivityTypeEnum.TYPE_DYNAMIC or activity.activity_sub_type != ActivitySubTypeEnum.SUBTYPE_DYNAMIC_HTML:
        raise HTTPException(status_code=404, detail="Interactive HTML activity not found")


async def reject_html_transfer(course_id: int, db: AsyncSession) -> None:
    existing = (await db.execute(select(Activity.id).where(
        Activity.course_id == course_id,
        Activity.activity_sub_type == ActivitySubTypeEnum.SUBTYPE_DYNAMIC_HTML,
    ).limit(1))).first()
    if existing:
        raise HTTPException(status_code=409, detail="Course copy and export do not yet support interactive HTML activities")


async def load_activity_and_course(activity_uuid: str, db: AsyncSession, *, lock: bool = False):
    query = select(Activity, Course).join(Course, Course.id == Activity.course_id).where(Activity.activity_uuid == activity_uuid)
    if lock:
        query = query.with_for_update()
    result = (await db.execute(query)).first()
    if result is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    activity, course = result
    require_html_activity(activity)
    return activity, course


async def read_html(request: Request, activity_uuid: str, user: object, db: AsyncSession) -> str:
    from src.services.courses.activities.activities import get_activity

    activity, course = await load_activity_and_course(activity_uuid, db)
    if not activity.published or not course.published:
        await require_html_editor(request, course, user, db)
    view = await get_activity(request, activity_uuid, user, db)
    if view.is_locked or view.content.get("paid_access") is False:
        raise HTTPException(status_code=403, detail="Activity is locked")
    row = (await db.execute(select(InteractiveHtml).where(InteractiveHtml.activity_id == activity.id))).scalars().first()
    return row.html if row is not None else ""


async def write_html(request: Request, activity_uuid: str, user: object, html: object, db: AsyncSession) -> str:
    activity, course = await load_activity_and_course(activity_uuid, db, lock=True)
    await require_html_editor(request, course, user, db)
    assert isinstance(user, PublicUser)
    html = validate_html(html)
    row = (await db.execute(select(InteractiveHtml).where(InteractiveHtml.activity_id == activity.id))).scalars().first()
    if row is None:
        row = InteractiveHtml(activity_id=activity.id, html=html)
    else:
        row.html = html
    activity.update_date = str(datetime.now())
    activity.last_modified_by_id = user.id
    db.add(activity)
    db.add(row)
    await db.commit()
    return html
