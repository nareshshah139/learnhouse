"""Add private interactive HTML activity source."""

from alembic import op
import sqlalchemy as sa

revision = "h20261116_interactive_html"
down_revision = "r20261006_recovery"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE activitysubtypeenum ADD VALUE IF NOT EXISTS 'SUBTYPE_DYNAMIC_HTML'")
    op.create_table(
        "interactivehtml",
        sa.Column("activity_id", sa.Integer(), sa.ForeignKey("activity.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("html", sa.Text(), nullable=False),
        if_not_exists=True,
    )


def downgrade():
    # PostgreSQL enum values cannot be removed without recreating the type.
    op.drop_table("interactivehtml")
