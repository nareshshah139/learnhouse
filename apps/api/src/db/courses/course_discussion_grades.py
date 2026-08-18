from typing import Optional

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, UniqueConstraint
from sqlmodel import Field, SQLModel


class CourseDiscussionGrade(SQLModel, table=True):
    """A staff-authored discussion score for one learner in one course week."""

    __table_args__ = (
        UniqueConstraint(
            "course_id",
            "user_id",
            "week_number",
            name="uq_course_discussion_grade_course_user_week",
        ),
        CheckConstraint("week_number >= 1", name="ck_course_discussion_grade_week"),
        CheckConstraint("max_score > 0", name="ck_course_discussion_grade_max_score"),
        CheckConstraint(
            "score >= 0 AND score <= max_score",
            name="ck_course_discussion_grade_score",
        ),
        Index("ix_course_discussion_grade_course_week", "course_id", "week_number"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("course.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    week_number: int
    score: int
    max_score: int = 100
    graded_by_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    creation_date: str
    update_date: str
