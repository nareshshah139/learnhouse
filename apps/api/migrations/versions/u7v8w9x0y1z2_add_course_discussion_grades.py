"""Add weekly course discussion grades.

Revision ID: u7v8w9x0y1z2
Revises: t6u7v8w9x0y1
Create Date: 2026-08-18 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "u7v8w9x0y1z2"
down_revision: Union[str, None] = "t6u7v8w9x0y1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Production currently bootstraps SQLModel metadata before Alembic is run.
    # If startup has already created this table, still let Alembic advance the
    # revision without attempting to create the same objects twice.
    if sa.inspect(op.get_bind()).has_table("coursediscussiongrade"):
        return
    op.create_table(
        "coursediscussiongrade",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "course_id",
            sa.Integer(),
            sa.ForeignKey("course.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("week_number", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("max_score", sa.Integer(), nullable=False, server_default="100"),
        sa.Column(
            "graded_by_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("creation_date", sa.String(), nullable=False),
        sa.Column("update_date", sa.String(), nullable=False),
        sa.CheckConstraint("week_number >= 1", name="ck_course_discussion_grade_week"),
        sa.CheckConstraint("max_score > 0", name="ck_course_discussion_grade_max_score"),
        sa.CheckConstraint(
            "score >= 0 AND score <= max_score",
            name="ck_course_discussion_grade_score",
        ),
        sa.UniqueConstraint(
            "course_id",
            "user_id",
            "week_number",
            name="uq_course_discussion_grade_course_user_week",
        ),
    )
    op.create_index(
        "ix_course_discussion_grade_course_week",
        "coursediscussiongrade",
        ["course_id", "week_number"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_course_discussion_grade_course_week",
        table_name="coursediscussiongrade",
    )
    op.drop_table("coursediscussiongrade")
