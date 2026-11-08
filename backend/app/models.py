from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    """Naive UTC (SQLite drops tzinfo anyway); the UI treats API datetimes as UTC."""
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "users"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    role: str = "member"  # admin | lead | member, see permissions.py (F7)
    email: Optional[str] = Field(default=None, index=True, unique=True)  # stored lower-cased
    password_hash: Optional[str] = None  # None = cannot log in
    is_active: bool = True
    created_at: Optional[datetime] = Field(default_factory=utcnow)


class RefreshToken(SQLModel, table=True):
    """Server side of the refresh cookie: only the SHA-256 of the token is stored. Rotated on every use."""

    __tablename__ = "refresh_tokens"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    token_hash: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime
    revoked_at: Optional[datetime] = None


class Meeting(SQLModel, table=True):
    __tablename__ = "meetings"
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    created_at: datetime = Field(default_factory=utcnow)
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    # scheduled -> live -> processing -> ready | failed
    status: str = "scheduled"
    created_by_id: Optional[int] = Field(default=None, foreign_key="users.id")
    room_name: str = ""
    egress_id: Optional[str] = None
    audio_path: Optional[str] = None
    duration_sec: Optional[int] = None
    summary: str = ""
    skipped_note: str = ""
    error: str = ""


class Segment(SQLModel, table=True):
    __tablename__ = "segments"
    id: Optional[int] = Field(default=None, primary_key=True)
    meeting_id: int = Field(foreign_key="meetings.id", index=True)
    start_sec: float = 0
    speaker: Optional[str] = None
    text: str


class DraftTask(SQLModel, table=True):
    """AI proposal. Lives only in the review queue until a human approves it (F6)."""

    __tablename__ = "draft_tasks"
    id: Optional[int] = Field(default=None, primary_key=True)
    meeting_id: int = Field(foreign_key="meetings.id", index=True)
    title: str
    description: str = ""
    acceptance_criteria: list = Field(default_factory=list, sa_column=Column(JSON))
    assignee_id: Optional[int] = Field(default=None, foreign_key="users.id")  # None = "not specified" (F5 AC2)
    due_text: Optional[str] = None  # None = "not specified"
    due_date: Optional[date] = None  # resolved calendar date, None if the wording was vague
    source_quote: str = ""
    status: str = "pending"  # pending | approved | rejected
    reviewer_id: Optional[int] = Field(default=None, foreign_key="users.id")
    reviewed_by_id: Optional[int] = Field(default=None, foreign_key="users.id")
    reviewed_at: Optional[datetime] = None
    task_id: Optional[int] = None


class Task(SQLModel, table=True):
    """Backlog / board task. Only created by an approved draft or by hand."""

    __tablename__ = "tasks"
    id: Optional[int] = Field(default=None, primary_key=True)
    number: int = Field(index=True, unique=True)  # shown as QAD-<number>
    title: str
    description: str = ""
    acceptance_criteria: list = Field(default_factory=list, sa_column=Column(JSON))
    assignee_id: Optional[int] = Field(default=None, foreign_key="users.id")
    due_text: Optional[str] = None
    due_date: Optional[date] = None
    status: str = "todo"  # todo | in_progress | done
    origin_meeting_id: Optional[int] = Field(default=None, foreign_key="meetings.id")
    origin_quote: str = ""
    created_by_id: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow)


class TaskEvent(SQLModel, table=True):
    """Activity history (F3)."""

    __tablename__ = "task_events"
    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="tasks.id", index=True)
    actor_id: Optional[int] = Field(default=None, foreign_key="users.id")
    text: str
    created_at: datetime = Field(default_factory=utcnow)
