"""Human review gate (F6). A draft becomes a Task only through `approve`."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, func, select

from ..db import get_session
from ..models import DraftTask, Meeting, Task, TaskEvent, User, utcnow
from ..schemas import DraftOut, DraftPatch, TaskOut
from ..security import require
from ..services.drafting import resolve_due_text
from ..serializers import draft_out, task_out

router = APIRouter(prefix="/api/drafts", tags=["review"])


def _pending_or_error(session: Session, draft_id: int) -> DraftTask:
    draft = session.get(DraftTask, draft_id)
    if not draft:
        raise HTTPException(404, "Черновик не найден")
    if draft.status != "pending":
        raise HTTPException(409, "Этот черновик уже обработан")
    return draft


@router.get("", response_model=list[DraftOut])
def list_drafts(
    status: Optional[str] = "pending",
    session: Session = Depends(get_session),
    _: User = Depends(require("drafts.read")),
):
    query = select(DraftTask).order_by(DraftTask.id)
    if status:
        query = query.where(DraftTask.status == status)
    return [draft_out(session, d) for d in session.exec(query).all()]


@router.patch("/{draft_id}", response_model=DraftOut)
def edit_draft(
    draft_id: int,
    body: DraftPatch,
    session: Session = Depends(get_session),
    _: User = Depends(require("drafts.review")),
):
    """Edit before approval (F6 AC1). `assignee_id: null` / `due_text: null` mean 'not specified'."""
    draft = _pending_or_error(session, draft_id)
    data = body.model_dump(exclude_unset=True)
    if "title" in data:
        data["title"] = (data["title"] or "").strip()
        if not data["title"]:
            raise HTTPException(422, "Название не может быть пустым")
    if data.get("assignee_id") is not None and not session.get(User, data["assignee_id"]):
        raise HTTPException(422, "Исполнитель не найден")
    if "acceptance_criteria" in data:
        data["acceptance_criteria"] = [c.strip() for c in (data["acceptance_criteria"] or []) if c.strip()]
    if "due_text" in data:
        data["due_text"] = (data["due_text"] or "").strip() or None
        if "due_date" not in data:  # reviewer retyped the wording -> recompute the date (None if vague)
            meeting = session.get(Meeting, draft.meeting_id)
            ref = ((meeting.started_at or meeting.created_at).date()) if meeting else None
            data["due_date"] = resolve_due_text(data["due_text"], ref)
    for key, value in data.items():
        setattr(draft, key, value)
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return draft_out(session, draft)


@router.post("/{draft_id}/approve", response_model=TaskOut, status_code=201)
def approve_draft(draft_id: int, session: Session = Depends(get_session), user: User = Depends(require("drafts.review"))):
    draft = _pending_or_error(session, draft_id)
    actor_id = user.id
    meeting = session.get(Meeting, draft.meeting_id)

    number = (session.exec(select(func.max(Task.number))).one() or 0) + 1
    task = Task(
        number=number,
        title=draft.title,
        description=draft.description,
        acceptance_criteria=list(draft.acceptance_criteria or []),
        assignee_id=draft.assignee_id,
        due_text=draft.due_text,
        due_date=draft.due_date,
        origin_meeting_id=draft.meeting_id,
        origin_quote=draft.source_quote,
        created_by_id=actor_id,
    )
    session.add(task)
    session.flush()
    session.add(TaskEvent(task_id=task.id, actor_id=actor_id, text=f"Принято со встречи «{meeting.title}»"))

    draft.status, draft.reviewed_by_id, draft.reviewed_at, draft.task_id = "approved", actor_id, utcnow(), task.id
    session.add(draft)
    session.commit()
    session.refresh(task)
    return task_out(session, task)


@router.post("/{draft_id}/reject", response_model=DraftOut)
def reject_draft(draft_id: int, session: Session = Depends(get_session), user: User = Depends(require("drafts.review"))):
    draft = _pending_or_error(session, draft_id)
    draft.status, draft.reviewed_by_id, draft.reviewed_at = "rejected", user.id, utcnow()
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return draft_out(session, draft)
