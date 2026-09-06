from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from src.core.events.database import get_db_session
from src.security.auth import get_current_user
from src.db.users import PublicUser, User
from src.db.user_organizations import UserOrganization
from src.db.communities.communities import Community
from src.db.communities.discussions import Discussion
from src.db.communities.discussion_comments import DiscussionComment
from src.db.communities.mention_notifications import MentionNotification
from src.services.communities.mentions import can_read

router = APIRouter()


def require_person(user):
    if not isinstance(user, PublicUser) or not user.id:
        raise HTTPException(401, 'Sign in to use mentions')


@router.get('/communities/{community_uuid}/mention-candidates')
async def candidates(community_uuid: str, request: Request, q: str = Query('', max_length=100),
                     current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db_session)):
    require_person(current_user)
    community = (await db.execute(select(Community).where(Community.community_uuid == community_uuid))).scalars().first()
    if not community or not await can_read(request, db, current_user, community):
        raise HTTPException(403, 'Community access required')
    from sqlalchemy import or_
    query = select(User).join(UserOrganization, UserOrganization.user_id == User.id).where(
        UserOrganization.org_id == community.org_id,
        or_(User.username.icontains(q, autoescape=True), User.first_name.icontains(q, autoescape=True), User.last_name.icontains(q, autoescape=True))
    ).order_by(User.username).limit(100)
    result = []
    for user in (await db.execute(query)).scalars().unique().all():
        if user.id != current_user.id and await can_read(request, db, user, community):
            result.append({'username': user.username, 'name': f'{user.first_name} {user.last_name}'.strip() or user.username})
        if len(result) == 10:
            break
    return result


@router.get('/mentions/notifications')
async def notifications(request: Request, org_id: int, current_user=Depends(get_current_user),
                        db: AsyncSession = Depends(get_db_session)):
    require_person(current_user)
    rows = (await db.execute(select(MentionNotification).join(Community, Community.id == MentionNotification.community_id).where(
        MentionNotification.recipient_id == current_user.id, Community.org_id == org_id
    ).order_by(MentionNotification.id.desc()).limit(100))).scalars().all()
    result = []
    for row in rows:
        community = await db.get(Community, row.community_id)
        if not community or not await can_read(request, db, current_user, community):
            continue
        discussion = await db.get(Discussion, row.discussion_id)
        actor = await db.get(User, row.actor_id)
        if not discussion or not actor:
            continue
        if row.source_uuid.startswith('comment_'):
            source = (await db.execute(select(DiscussionComment).where(DiscussionComment.comment_uuid == row.source_uuid))).scalars().first()
            if not source:
                continue
        result.append({'id': row.id, 'read': row.read, 'created_at': row.created_at,
            'actor': f'{actor.first_name} {actor.last_name}'.strip() or actor.username,
            'title': discussion.title,
            'href': f'/community/{community.community_uuid.removeprefix("community_")}/discussion/{discussion.discussion_uuid.removeprefix("discussion_")}#{row.source_uuid}'})
    return result


@router.patch('/mentions/notifications/{notification_id}/read')
async def mark_read(notification_id: int, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db_session)):
    require_person(current_user)
    row = await db.get(MentionNotification, notification_id)
    if not row or row.recipient_id != current_user.id:
        raise HTTPException(404, 'Notification not found')
    row.read = True
    db.add(row)
    await db.commit()
    return {'success': True}
