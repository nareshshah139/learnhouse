"""Add one current admin recovery grant per user."""

from alembic import op
import sqlalchemy as sa

revision = "r20261006_recovery"
down_revision = "m20260906_mentions"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("recoverygrant"):
        return
    op.create_table(
        "recoverygrant",
        sa.Column("target_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("issuer_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", sa.Integer(), sa.ForeignKey("organization.id", ondelete="CASCADE"), nullable=False),
        sa.Column("issuer_membership_id", sa.Integer(), nullable=False),
        sa.Column("target_membership_id", sa.Integer(), nullable=False),
        sa.Column("secret_digest", sa.String(64), unique=True, nullable=False),
        sa.Column("issuer_fingerprint", sa.String(64), nullable=False),
        sa.Column("target_fingerprint", sa.String(64), nullable=False),
        sa.Column("policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("recoverygrant")
