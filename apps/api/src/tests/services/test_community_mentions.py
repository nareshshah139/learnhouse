import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlmodel import select
from src.db.communities.communities import Community
from src.db.communities.discussions import Discussion
from src.db.communities.discussion_comments import DiscussionComment
from src.db.communities.mention_notifications import MentionNotification
from src.db.user_organizations import UserOrganization
from src.services.communities.mentions import mention_names, create_mentions, can_read
from src.routers.communities.mentions import candidates, notifications, mark_read


@pytest.mark.parametrize('text,expected', [
    ('Hello @Alice, @bob. @ALICE', {'alice', 'bob'}),
    ('a@alice.com https://site/@bob `@code` ```@block```', set()),
    ('(@first.last) @some-user!', {'first.last', 'some-user'}),
    ('', set()),
    (json.dumps({'type': 'doc', 'content': [
        {'type': 'paragraph', 'content': [{'type': 'text', 'text': '@regular', 'marks': [{'type': 'link', 'attrs': {'href': '@hidden'}}]}]},
        {'type': 'codeBlock', 'content': [{'type': 'text', 'text': '@code'}]},
        {'type': 'paragraph', 'content': [{'type': 'text', 'text': '@inline', 'marks': [{'type': 'code'}]}]},
    ]}), {'regular'}),
])
def test_parser(text, expected):
    assert mention_names(text) == expected


@pytest.fixture
async def discussion(db, org, admin_user):
    community = Community(name='Team', org_id=org.id, community_uuid='community_test')
    db.add(community)
    await db.flush()
    discussion = Discussion(title='Project', community_id=community.id, org_id=org.id,
                            author_id=admin_user.id, discussion_uuid='discussion_test')
    db.add(discussion)
    await db.commit()
    return discussion


async def test_atomic_deduplicated_mentions(db, discussion, admin_user, regular_user):
    with patch('src.services.communities.mentions.check_resource_access', new=AsyncMock()):
        await create_mentions(None, db, admin_user, discussion, 'discussion_test', '@regular @admin')
        await create_mentions(None, db, admin_user, discussion, 'discussion_test', '@REGULAR')
        rows = (await db.execute(select(MentionNotification))).scalars().all()
        assert len(rows) == 1
        assert rows[0].recipient_id == regular_user.id
        await db.rollback()
        assert (await db.execute(select(MentionNotification))).scalars().all() == []


async def test_denied_and_nonmember_not_notified(db, discussion, admin_user, regular_user):
    with patch('src.services.communities.mentions.check_resource_access', new=AsyncMock(side_effect=HTTPException(403))):
        await create_mentions(None, db, admin_user, discussion, 'discussion_test', '@regular')
    assert (await db.execute(select(MentionNotification))).scalars().all() == []
    membership = (await db.execute(select(UserOrganization).where(UserOrganization.user_id == regular_user.id))).scalars().one()
    await db.delete(membership)
    await db.commit()
    with patch('src.services.communities.mentions.check_resource_access', new=AsyncMock()) as check:
        community = await db.get(Community, discussion.community_id)
        assert not await can_read(None, db, regular_user, community)
        await create_mentions(None, db, admin_user, discussion, 'discussion_test', '@regular')
        check.assert_not_called()
    assert (await db.execute(select(MentionNotification))).scalars().all() == []


async def test_inbox_ownership_and_revocation(db, org, discussion, admin_user, regular_user):
    with patch('src.services.communities.mentions.check_resource_access', new=AsyncMock()):
        await create_mentions(None, db, admin_user, discussion, 'discussion_test', '@regular')
        await db.commit()
        items = await notifications(None, org.id, regular_user, db)
        assert len(items) == 1
        assert items[0]['href'] == '/community/test/discussion/test#discussion_test'
        assert await notifications(None, org.id, admin_user, db) == []
        assert await notifications(None, org.id + 1, regular_user, db) == []
        with pytest.raises(HTTPException) as exc:
            await mark_read(items[0]['id'], admin_user, db)
        assert exc.value.status_code == 404
        await mark_read(items[0]['id'], regular_user, db)
        assert (await notifications(None, org.id, regular_user, db))[0]['read']
    with patch('src.services.communities.mentions.check_resource_access', new=AsyncMock(side_effect=HTTPException(403))):
        assert await notifications(None, org.id, regular_user, db) == []


async def test_candidates_and_deleted_comment(db, org, discussion, admin_user, regular_user):
    with patch('src.services.communities.mentions.check_resource_access', new=AsyncMock()):
        found = await candidates('community_test', None, 'reg', admin_user, db)
        assert found == [{'username': 'regular', 'name': 'Regular User'}]
        comment = DiscussionComment(discussion_id=discussion.id, author_id=admin_user.id,
                                     comment_uuid='comment_test', content='@regular')
        db.add(comment)
        await db.flush()
        await create_mentions(None, db, admin_user, discussion, 'comment_test', '@regular')
        await db.commit()
        assert len(await notifications(None, org.id, regular_user, db)) == 1
        assert (await notifications(None, org.id, regular_user, db))[0]['preview'] == '@regular'
        await db.delete(comment)
        await db.commit()
        assert await notifications(None, org.id, regular_user, db) == []


async def test_limit(db, discussion, admin_user):
    with pytest.raises(HTTPException) as exc:
        await create_mentions(None, db, admin_user, discussion, 'discussion_test', ' '.join(f'@user{i}' for i in range(21)))
    assert exc.value.status_code == 400
