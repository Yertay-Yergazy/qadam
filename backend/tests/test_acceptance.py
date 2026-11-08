"""Acceptance checks with failure cases (US3 / US4 / US7).

Assumed mapping (adjust the labels to your backlog wording if it differs):
  US3 - the lead reviews AI drafts: edit, approve; only approved drafts become tasks.
  US4 - the lead rejects wrong drafts; nothing unreviewed or rejected reaches backlog/board.
  US7 - a task that came from a meeting says so (meeting title is returned for the "from meeting" label).
"""
from conftest import ADMIN, LEAD, MEMBER, login
from app.services import pipeline


def _new_meeting_with_drafts(client, text="Алия: Нужно обновить документацию. Алия: Надо починить логин."):
    m = client.post("/api/meetings", json={"title": "Стендап"}).json()
    assert client.post(f"/api/meetings/{m['id']}/transcript", json={"text": text}).status_code == 202
    return m["id"]


# ------------------------------------------------------------------ US3 approve / edit
def test_us3_approve_creates_exactly_one_task_with_origin(client):
    draft = client.get("/api/drafts").json()[0]
    before = len(client.get("/api/tasks").json())
    task = client.post(f"/api/drafts/{draft['id']}/approve").json()
    assert len(client.get("/api/tasks").json()) == before + 1
    assert task["origin_meeting_id"] == draft["meeting_id"] and task["origin_quote"] == draft["source_quote"]


def test_us3_failure_double_approve_does_not_duplicate(client):
    draft = client.get("/api/drafts").json()[0]
    assert client.post(f"/api/drafts/{draft['id']}/approve").status_code == 201
    before = len(client.get("/api/tasks").json())
    assert client.post(f"/api/drafts/{draft['id']}/approve").status_code == 409
    assert len(client.get("/api/tasks").json()) == before


def test_us3_failure_empty_title_is_refused_and_draft_stays_pending(client):
    draft = client.get("/api/drafts").json()[0]
    assert client.patch(f"/api/drafts/{draft['id']}", json={"title": "   "}).status_code == 422
    assert client.get("/api/drafts").json()[0]["title"] == draft["title"]


def test_us3_failure_unknown_assignee_is_refused(client):
    draft = client.get("/api/drafts").json()[0]
    assert client.patch(f"/api/drafts/{draft['id']}", json={"assignee_id": 9999}).status_code == 422


def test_us3_failure_approve_unknown_draft_is_404(client):
    assert client.post("/api/drafts/9999/approve").status_code == 404


def test_us3_failure_member_cannot_approve(anon):
    draft_id = anon.get("/api/drafts", headers=login(anon, MEMBER)).json()[0]["id"]
    r = anon.post(f"/api/drafts/{draft_id}/approve", headers=login(anon, MEMBER))
    assert r.status_code == 403
    assert len(anon.get("/api/tasks", headers=login(anon, LEAD)).json()) == 3  # nothing was created


def test_us3_retyped_due_wording_recomputes_the_date(client):
    draft = client.get("/api/drafts").json()[0]
    r = client.patch(f"/api/drafts/{draft['id']}", json={"due_text": "завтра"}).json()
    assert r["due_text"] == "завтра" and r["due_date"] is not None
    r = client.patch(f"/api/drafts/{draft['id']}", json={"due_text": "когда получится"}).json()
    assert r["due_date"] is None


# ------------------------------------------------------------------ US4 reject / nothing unreviewed on the board
def test_us4_reject_removes_from_queue_and_creates_no_task(client):
    draft = client.get("/api/drafts").json()[0]
    before = len(client.get("/api/tasks").json())
    assert client.post(f"/api/drafts/{draft['id']}/reject").status_code == 200
    assert client.get("/api/drafts").json() == []
    assert len(client.get("/api/tasks").json()) == before


def test_us4_failure_rejected_draft_cannot_be_approved_later(client):
    draft = client.get("/api/drafts").json()[0]
    client.post(f"/api/drafts/{draft['id']}/reject")
    assert client.post(f"/api/drafts/{draft['id']}/approve").status_code == 409
    assert client.post(f"/api/drafts/{draft['id']}/reject").status_code == 409


def test_us4_failure_member_cannot_reject(anon):
    draft_id = anon.get("/api/drafts", headers=login(anon, MEMBER)).json()[0]["id"]
    assert anon.post(f"/api/drafts/{draft_id}/reject", headers=login(anon, MEMBER)).status_code == 403
    assert len(anon.get("/api/drafts", headers=login(anon, LEAD)).json()) == 1  # still pending


def test_us4_new_meeting_drafts_stay_off_the_board_until_approved(client):
    tasks_before = len(client.get("/api/tasks").json())
    _new_meeting_with_drafts(client)
    assert len(client.get("/api/drafts").json()) == 3  # 1 seeded + 2 new
    assert len(client.get("/api/tasks").json()) == tasks_before


def test_us4_failed_transcription_creates_no_tasks(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("whisper down")

    monkeypatch.setattr(pipeline, "transcribe_file", boom)
    m = client.post("/api/meetings", json={"title": "Сломанная"}).json()
    client.post(f"/api/meetings/{m['id']}/audio", files={"file": ("a.ogg", b"x", "audio/ogg")})
    detail = client.get(f"/api/meetings/{m['id']}").json()
    assert detail["status"] == "failed" and detail["error"]
    assert detail["drafts"] == [] and len(client.get("/api/tasks").json()) == 3


# ------------------------------------------------------------------ US7 "from meeting" label
def test_us7_task_from_meeting_exposes_meeting_title_manual_task_does_not(client):
    draft = client.get("/api/drafts").json()[0]
    from_meeting = client.post(f"/api/drafts/{draft['id']}/approve").json()
    manual = client.post("/api/tasks", json={"title": "Руками"}).json()
    by_id = {t["id"]: t for t in client.get("/api/tasks").json()}
    assert by_id[from_meeting["id"]]["origin_meeting_title"] == "Планирование спринта"
    assert by_id[manual["id"]]["origin_meeting_id"] is None and by_id[manual["id"]]["origin_meeting_title"] is None
