from sqlalchemy import Column, ForeignKey, Integer, Text
from sqlmodel import Field, SQLModel


class InteractiveHtml(SQLModel, table=True):
    activity_id: int = Field(
        sa_column=Column(Integer, ForeignKey("activity.id", ondelete="CASCADE"), primary_key=True)
    )
    html: str = Field(sa_column=Column(Text, nullable=False))
