"""Persistent community mention notifications."""
from alembic import op
import sqlalchemy as sa

revision = 'm20260906_mentions'
down_revision = 'u7v8w9x0y1z2'
branch_labels = None
depends_on = None


def upgrade():
    # Some deployments create new model tables at startup before running Alembic.
    if sa.inspect(op.get_bind()).has_table('mentionnotification'):
        return
    op.create_table('mentionnotification',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('recipient_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('community_id', sa.Integer(), sa.ForeignKey('community.id', ondelete='CASCADE'), nullable=False),
        sa.Column('discussion_id', sa.Integer(), sa.ForeignKey('discussion.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_uuid', sa.String(), nullable=False),
        sa.Column('read', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.UniqueConstraint('recipient_id', 'source_uuid', name='uq_mention_recipient_source'))
    op.create_index('ix_mentionnotification_recipient_id', 'mentionnotification', ['recipient_id'])


def downgrade():
    op.drop_table('mentionnotification')
