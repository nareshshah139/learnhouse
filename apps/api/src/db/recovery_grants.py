from datetime import datetime

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlmodel import Field, SQLModel


class RecoveryGrant(SQLModel, table=True):
    target_id: int = Field(sa_column=Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), primary_key=True))
    issuer_id: int = Field(sa_column=Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False))
    org_id: int = Field(sa_column=Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False))
    issuer_membership_id: int
    target_membership_id: int
    secret_digest: str = Field(sa_column=Column(String(64), unique=True, nullable=False))
    issuer_fingerprint: str = Field(sa_column=Column(String(64), nullable=False))
    target_fingerprint: str = Field(sa_column=Column(String(64), nullable=False))
    policy_fingerprint: str = Field(sa_column=Column(String(64), nullable=False))
    issued_at: datetime
    expires_at: datetime
