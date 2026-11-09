"""Hand-off recording -> transcription -> draft tasks (task N7 / competency C9).

Failure never loses the record (F4 AC2): the meeting is marked `failed` with a readable reason,
and the UI then offers manual audio / transcript upload.
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlmodel import Session, delete, select

from ..config import get_settings
from ..db import engine
from ..models import DraftTask, Meeting, Segment, User, utcnow
from .drafting import SegmentIn, get_drafter
from .transcription import transcribe_file

log = logging.getLogger("qadam.pipeline")


def generate_drafts(session: Session, meeting: Meeting) -> None:
    """Run the NLP step on the stored transcript and (re)create the pending drafts."""
    segs = session.exec(
        select(Segment).where(Segment.meeting_id == meeting.id).order_by(Segment.start_sec, Segment.id)
    ).all()
    users = session.exec(select(User)).all()
    by_name = {u.name: u for u in users}
    lead = next((u for u in users if u.role == "lead"), None)

    result = get_drafter(get_settings().drafter).generate(
        [SegmentIn(s.start_sec, s.speaker, s.text) for s in segs],
        list(by_name),
        today=(meeting.started_at or meeting.created_at).date(),
    )

    # Reprocessing replaces untouched proposals only; reviewed ones stay as history.
    session.exec(delete(DraftTask).where(DraftTask.meeting_id == meeting.id, DraftTask.status == "pending"))
    for p in result.drafts:
        assignee = by_name.get(p.assignee_name) if p.assignee_name else None
        session.add(
            DraftTask(
                meeting_id=meeting.id,
                title=p.title,
                description=p.description,
                acceptance_criteria=p.acceptance_criteria,
                assignee_id=assignee.id if assignee else None,
                due_text=p.due_text,
                due_date=p.due_date,
                source_quote=p.source_quote,
                reviewer_id=lead.id if lead else None,
            )
        )
    meeting.summary = result.summary or (
        f"Транскрипт готов: {len(segs)} фраз, задач автоматически не найдено. "
        "Проверьте транскрипт и при необходимости создайте задачи вручную."
        if segs
        else "Речь не распознана."
    )
    topics = ", ".join(result.skipped)
    meeting.skipped_note = f"Не создано — {topics}. На встрече не было решения." if topics else ""


def run_pipeline(meeting_id: int, transcribe: bool = True) -> None:
    """Background job. Opens its own session (the request session is closed by then)."""
    with Session(engine) as session:
        try:
            meeting = session.get(Meeting, meeting_id)
            meeting.status, meeting.error = "processing", ""
            session.add(meeting)
            session.commit()

            if transcribe:
                if not meeting.audio_path or not Path(meeting.audio_path).exists():
                    raise FileNotFoundError("Файл записи не найден")
                result = transcribe_file(Path(meeting.audio_path))
                session.exec(delete(Segment).where(Segment.meeting_id == meeting_id))
                for seg in result.segments:
                    session.add(
                        Segment(meeting_id=meeting_id, start_sec=seg.start_sec, speaker=seg.speaker, text=seg.text)
                    )
                meeting.duration_sec = int(result.duration)
                session.commit()
                if not result.segments:
                    raise ValueError("В записи не удалось распознать речь")

            generate_drafts(session, meeting)
            meeting.status = "ready"
            session.add(meeting)
            session.commit()
        except Exception as exc:  # noqa: BLE001 - any failure must end in a visible state
            log.exception("Pipeline failed for meeting %s", meeting_id)
            session.rollback()
            meeting = session.get(Meeting, meeting_id)
            meeting.status = "failed"
            meeting.error = (str(exc) or exc.__class__.__name__)[:500]
            meeting.ended_at = meeting.ended_at or utcnow()
            session.add(meeting)
            session.commit()
