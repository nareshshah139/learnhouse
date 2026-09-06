# Community mentions

Type `@` followed by a username in a discussion body or reply, then select a member. You can also type the complete `@username` directly. Posting or saving an edit creates an in-app notification for eligible recipients. The bell in the organization navigation opens the inbox; notifications link back to the discussion or reply and can be marked as read.

Only members of the same organization who can read the community are suggested or notified. Inbox reads recheck community access. Deleted discussions cascade-delete their notifications; deleted replies are omitted from the inbox. Self-mentions, email addresses, code blocks, inline code, and rich-text attributes do not notify. Each recipient gets at most one notification per discussion/reply, including edits. At most 20 distinct usernames may be mentioned per post. Existing content is not backfilled. The inbox shows the latest 100 notifications and refreshes every 30 seconds.

This release provides in-app notifications, not email or browser push notifications. Literal usernames are stored in content; later username changes do not rewrite old posts. Existing community and assignment permissions are unchanged.

## Deployment

The `MentionNotification` model creates the new table on deployments using the existing startup `create_all` path. Alembic migration `m20260906_mentions` supports migration-managed deployments and recognizes a table already created at startup. No existing content or grade data is modified.

## Tests

`cd apps/api && python -m pytest src/tests/services/test_community_mentions.py src/tests/services/test_community_comments_votes_service.py src/tests/services/test_communities_service.py -q`

Covers parsing, transaction rollback, duplicates, self-mentions, membership, denied access, inbox ownership, access revocation, deleted replies, candidate search, and mention limits.
