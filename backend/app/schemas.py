from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field

from .permissions import Role

TaskStatus = Literal["todo", "in_progress", "done"]


# ------------------------------------------------------------------ auth / users
class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    """Public profile: what every team member may see about a colleague."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    role: str
    is_active: bool = True


class UserAdminOut(UserOut):
    email: Optional[str]
    created_at: Optional[datetime]


class MeOut(UserAdminOut):
    permissions: list[str]


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: MeOut


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Role = "member"


class UserUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    email: Optional[EmailStr] = None
    role: Optional[Role] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    start_sec: float
    speaker: Optional[str]
    text: str


class DraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    meeting_id: int
    title: str
    description: str
    acceptance_criteria: list[str]
    assignee_id: Optional[int]
    due_text: Optional[str]
    due_date: Optional[date] = None
    source_quote: str
    status: str
    reviewer_id: Optional[int]
    meeting_title: str = ""
    meeting_date: Optional[datetime] = None
    meeting_skipped_note: str = ""


class DraftPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    acceptance_criteria: Optional[list[str]] = None
    assignee_id: Optional[int] = None
    due_text: Optional[str] = None
    due_date: Optional[date] = None


class MeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class MeetingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    created_at: datetime
    status: str
    created_by_id: Optional[int] = None
    summary: str
    skipped_note: str
    error: str
    duration_sec: Optional[int]
    room_name: str
    recording: bool = False
    pending_drafts: int = 0


class MeetingDetail(MeetingOut):
    segments: list[SegmentOut] = []
    drafts: list[DraftOut] = []


class TranscriptIn(BaseModel):
    text: str = Field(min_length=1)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    assignee_id: Optional[int] = None
    due_text: Optional[str] = None


class TaskPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    assignee_id: Optional[int] = None
    due_text: Optional[str] = None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    actor_id: Optional[int]
    text: str
    created_at: datetime


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    number: int
    title: str
    description: str
    acceptance_criteria: list[str]
    assignee_id: Optional[int]
    due_text: Optional[str]
    due_date: Optional[date] = None
    status: str
    origin_meeting_id: Optional[int]
    origin_quote: str
    created_by_id: Optional[int] = None
    created_at: datetime
    origin_meeting_title: Optional[str] = None
    origin_meeting_date: Optional[datetime] = None

    @computed_field
    @property
    def key(self) -> str:
        return f"QAD-{self.number}"


class TaskDetail(TaskOut):
    events: list[EventOut] = []
