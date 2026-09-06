from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class MentionNotification(SQLModel, table=True):
    __table_args__ = (UniqueConstraint('recipient_id', 'source_uuid', name='uq_mention_recipient_source'),)
    id: Optional[int] = Field(default=None, primary_key=True)
    recipient_id: int = Field(foreign_key='user.id', ondelete='CASCADE', index=True)
    actor_id: int = Field(foreign_key='user.id', ondelete='CASCADE')
    community_id: int = Field(foreign_key='community.id', ondelete='CASCADE')
    discussion_id: int = Field(foreign_key='discussion.id', ondelete='CASCADE')
    source_uuid: str
    read: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
