"""Mentions use literal @usernames; rich-text attributes and code are ignored."""
import json
import re
from fastapi import HTTPException
from sqlmodel import select
from src.db.users import User, PublicUser
from src.db.user_organizations import UserOrganization
from src.db.communities.communities import Community
from src.db.communities.mention_notifications import MentionNotification
from src.security.rbac import check_resource_access, AccessAction


def visible_text(content):
    if not content:
        return ''
    def visible(node):
        if not isinstance(node, dict) or node.get('type') in ('codeBlock', 'code'):
            return ''
        if any(m.get('type') == 'code' for m in node.get('marks', [])):
            return ''
        return node.get('text', '') + ''.join(visible(c) for c in node.get('content', [])) + ('\n' if node.get('type') == 'paragraph' else '')
    try:
        doc = json.loads(content)
    except (ValueError, TypeError):
        doc = None
    text = visible(doc) if isinstance(doc, dict) and doc.get('type') == 'doc' else content
    text = re.sub(r'```[\s\S]*?```|`[^`]*`', '', text)
    return text


def mention_names(content):
    return {m.rstrip('.-').casefold() for m in re.findall(r'(?<![\w@/])@([\w][\w.-]{0,99})(?![\w@])', visible_text(content))}


async def can_read(request, db, user, community):
    membership = (await db.execute(select(UserOrganization.id).where(
        UserOrganization.user_id == user.id, UserOrganization.org_id == community.org_id))).first()
    if not membership:
        return False
    try:
        await check_resource_access(request, db, PublicUser.model_validate(user.model_dump()), community.community_uuid, AccessAction.READ)
        return True
    except HTTPException as exc:
        if exc.status_code in (403, 404):
            return False
        raise


async def create_mentions(request, db, actor, discussion, source_uuid, content):
    from src.security.auth import resolve_acting_user_id
    actor_id = resolve_acting_user_id(actor)
    names = mention_names(content)
    if not names:
        return
    if len(names) > 20:
        raise HTTPException(400, 'Please mention at most 20 people per post.')
    community = await db.get(Community, discussion.community_id)
    if not community:
        return
    from sqlalchemy import func
    users = (await db.execute(select(User).join(UserOrganization, UserOrganization.user_id == User.id).where(
        UserOrganization.org_id == community.org_id, func.lower(User.username).in_(names)))).scalars().unique().all()
    # One notification per recipient per source, including edits and concurrent saves.
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    insert = sqlite_insert if db.bind.dialect.name == 'sqlite' else pg_insert
    for user in users[:20]:
        if user.id == actor_id or not await can_read(request, db, user, community):
            continue
        notification = MentionNotification(recipient_id=user.id, actor_id=actor_id,
            community_id=community.id, discussion_id=discussion.id, source_uuid=source_uuid)
        values = notification.model_dump(exclude={'id'})
        await db.execute(insert(MentionNotification).values(**values).on_conflict_do_nothing(
            index_elements=['recipient_id', 'source_uuid']))
