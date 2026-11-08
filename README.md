# Qadam — MVP
<img width="1823" height="913" alt="изображение" src="https://github.com/user-attachments/assets/9cccea1f-888b-40ad-b751-da2f85ded86b" />
<img width="1811" height="933" alt="изображение" src="https://github.com/user-attachments/assets/34a1d712-54c0-408b-9ba2-79ae4dc315b3" />


Meeting-to-task platform: **audio call → recording → Whisper transcript → AI draft tasks → human review → backlog / board.**

| Layer | Tech |
| --- | --- |
| Frontend | React 18 + Vite + React Router, **Mantine 7** UI kit (official Figma community kit uses the same tokens) + Tabler icons, light/dark theme |
| Auth / RBAC | JWT access token (in memory) + rotating refresh token (httpOnly cookie), bcrypt, roles admin / lead / member |
| Backend | Python 3.11+, FastAPI, SQLModel (SQLite by default, any SQLAlchemy URL works) |
| Audio calls | **LiveKit** (SDK chosen in T6): `livekit-client` in the browser, `livekit-api` + Egress on the server |
| Transcription | **faster-whisper** (CTranslate2 build of OpenAI Whisper), runs on your own hardware |
| NLP (draft tasks) | Rule-based drafter by default; experimental self-hosted LLM drafter (Qwen + llama.cpp) behind `DRAFTER=llm`, see below |

## What is implemented (MVP = F1, F3, F4, F5-interface, F6)

| Feature (A2) | Where |
| --- | --- |
| **F4** In-app audio call + transcription | `CallPage.jsx`, `routers/calls.py`, `services/livekit_service.py`, `services/transcription.py`. Failure shows a visible error and offers manual audio / text upload (F4 AC2). |
| **F5** Draft tasks from transcript | `services/drafting.py` (interface), `services/pipeline.py`. Never invents assignee / due date → "не указан" (F5 AC2). |
| **F6** Human review gate | `ReviewPage.jsx`, `routers/drafts.py`. Edit / approve / reject. Unreviewed drafts exist *only* in the review queue, never in backlog or board (F6 AC2). |
| **F1** Backlog + Kanban board | `BacklogPage.jsx`, `BoardPage.jsx` (drag & drop), `routers/tasks.py`, manual task creation as the pilot fallback. |
| **F3** Task detail + activity history | `components/TaskModal.jsx`, `TaskEvent` model. |
| **F7** Login + roles (RBAC) | `security.py`, `permissions.py`, `routers/auth.py`, `routers/users.py`, `LoginPage.jsx`, `TeamPage.jsx`. See below. |

Screens map 1:1 to the mock: **Звонок** (5), **Встречи** (1), **Проверка** (2), **Задачи** (3), **Доска** (4), plus **Вход** and **Команда** (admin only).

## Auth & roles (F7)

Demo users (with `SEED_DEMO=true`), password `qadam-demo` (`DEMO_PASSWORD`):

| User | E-mail | Role |
| --- | --- | --- |
| Алия | aliya@qadam.kz | admin |
| Ерлан | erlan@qadam.kz | lead |
| Айгерим | aigerim@qadam.kz | member |

For a real deployment set `SEED_DEMO=false`, `JWT_SECRET`, `ADMIN_EMAIL` / `ADMIN_PASSWORD` (the first admin is created on startup), and `COOKIE_SECURE=true` behind HTTPS. Further users are added by an admin on **Команда**.

| Permission | member | lead | admin |
| --- | :-: | :-: | :-: |
| See meetings, drafts, tasks, team | ✓ | ✓ | ✓ |
| Create meetings, join calls, create tasks | ✓ | ✓ | ✓ |
| Upload audio/transcript, reprocess, end call | own meetings | any | any |
| Edit / move tasks | assigned to or created by them | any | any |
| Approve / edit / reject AI drafts (F6) | — | ✓ | ✓ |
| Manage users, roles, passwords | — | — | ✓ |

The table lives in one place: `backend/app/permissions.py`. Endpoints use `Depends(require("<permission>"))`; ownership checks sit next to the endpoint. The frontend hides controls using the permission list from `/api/auth/me`, but the API is what enforces it.

How sessions work:
- `POST /api/auth/login` → access JWT (15 min) in the body, refresh token in an `httpOnly`, `SameSite=Strict` cookie scoped to `/api/auth`. The browser keeps the access token in memory only.
- On 401 the frontend calls `POST /api/auth/refresh` once (the refresh token is rotated). Re-use of an old refresh token revokes all sessions of that user.
- The role and `is_active` are read from the DB on every request: a demotion or deactivation applies immediately.
- The actor (who approved a draft, who moved a task, who joins a call) comes from the token; the API no longer accepts a `user_id` from the client.
- 5 failed logins per IP+e-mail in 15 min → 429. Passwords: bcrypt (SHA-256 pre-hash, so >72-byte passwords are fully used).
- An existing SQLite DB from before auth is migrated on startup (new columns are added; demo users get their e-mail/password).

Deliberately *not* in this MVP (per A2/A4): sprints (F2), transcript-snippet traceability beyond the quote on the review card (F9), video/screen share (F11), speaker diarization (see limitations).

## Run it

### 1. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp ../.env.example .env
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs. On first start the DB is seeded with the demo data from the mock (users Алия / Ерлан / Айгерим, the "Планирование спринта" meeting, one pending AI draft, three backlog tasks). Turn off with `SEED_DEMO=false`.

The Whisper model downloads on the first transcription (`small` ≈ 500 MB). Use `WHISPER_MODEL=tiny` for quick tests, `large-v3` + `WHISPER_DEVICE=cuda` if you have a GPU.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173, /api is proxied to :8000
```

### 3. Audio calls (LiveKit + recording)

```bash
mkdir -p data/recordings && chmod 777 data/recordings     # the egress container writes here
docker compose up livekit egress redis
```

Run the backend locally (step 1) with `LIVEKIT_API_URL=http://localhost:7880`, **or** run everything including the backend in Docker: `docker compose up --build`.

LiveKit calls the backend webhook at `http://backend:8000/api/livekit/webhook` (set in `livekit.yaml`). If you run the backend *outside* Docker, change that URL to `http://host.docker.internal:8000/api/livekit/webhook`.

Open Qadam in two browser tabs, pick different users in the sidebar, start a call in one and join from the other (Звонок → «Идут сейчас»). **«Завершить для всех»** closes the room → Egress finalises the OGG → webhook → Whisper → drafts appear in **Проверка**.

Without LiveKit (empty `LIVEKIT_API_KEY`) the app still works end to end through **Звонок → Загрузить запись** (any audio file) or by pasting a transcript.

### Tests

```bash
cd backend && python -m pytest
```

## How a recording becomes tasks

```
browser (livekit-client) ──join token──▶ POST /api/meetings/{id}/call/token
        │ WebRTC
     LiveKit ──room_started webhook──▶ backend starts audio-only Egress → data/recordings/*.ogg
        │ call ends (POST …/call/end or room empties)
     LiveKit ──egress_ended webhook──▶ backend: status=processing, background job:
                                        faster-whisper → Segment rows → DraftGenerator → DraftTask rows
                                        status=ready  (or failed + reason; nothing is silently lost)
review UI ──approve──▶ Task (QAD-n) + activity event  → backlog and board
```

## Drafting: rules or a self-hosted LLM

Everything the rest of the app needs is the `DraftGenerator` protocol in `backend/app/services/drafting.py`;
`DRAFTER` picks the implementation:

| `DRAFTER` | What drafts the tasks |
| --- | --- |
| `placeholder` (default) | `RuleDrafter`: keyword/regex rules (ru + en): «давайте / надо / нужно», «пусть сделает <имя>», weekdays, «готово, когда …». Deterministic, no network |
| `llm` | `LLMDrafter`: a small self-hosted model (Qwen via llama.cpp) behind an OpenAI-compatible API; falls back to the rules on any failure |
| `none` | no drafts |

Re-run any drafter on stored transcripts with **«Пересоздать черновики»** (`POST /api/meetings/{id}/reprocess`).

### LLM drafter (`DRAFTER=llm`) — experimental, off by default

```
Segment rows ─► sentences ─► windows around cue sentences ─► llama-server (JSON schema) ─► guards ─► DraftTask
```

* **The model proposes, code checks, a human approves.** The guards enforce F5 AC2 regardless of what the model says:
  an assignee must be a teammate *named* in the task's own lines (a speaker label is not an assignment), a deadline
  must have been said and is dated by the rules, criteria and titles must be grounded in the transcript, the quote
  is cut from the transcript by code. Server down, timeout or broken JSON → the rule drafter, nothing is lost.
* Code: `services/llm_drafting.py` (pipeline + guards), `services/llm_prompts.py` (prompts per language — small
  models follow the prompt's language, so English meetings get an English prompt; Kazakh goes with the Russian one).
* Settings: `LLM_BASE_URL`, `LLM_MODEL` (Ollama needs the tag, llama-server ignores it), `LLM_MODE`
  (`extract` default, `refine`, `full`), `LLM_TIMEOUT_SEC` — see `.env.example`.
* Run locally: put a GGUF model into `data/models/` and start the `llm` compose profile:
  ```bash
  curl -L -o data/models/Qwen3-1.7B-Q4_K_M.gguf \
    https://huggingface.co/unsloth/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q4_K_M.gguf
  DRAFTER=llm docker compose --profile llm up --build
  ```
* **Status:** the model is not chosen yet, so production keeps `DRAFTER=placeholder`. The dev stand has 1 vCPU and
  ~2 GB for the whole project; Qwen3-1.7B Q4_K_M needs ~1.45 GB RSS and ~5–10 s per fragment on one core. Quality is
  measured with `backend/eval` (12 real meetings ru/en + synthetic cases, see `backend/eval/README.md`); on real
  meetings no model up to 2B parameters reaches the targets yet, mostly because of false positives.

## Known limitations

- **No speaker labels from calls.** The recording is one mixed audio track, so Whisper segments have no speaker. Per-participant track recording or diarization is the next step; until then the transcript shows text and timestamps only (manual transcripts with `Имя: текст` do keep names).
- **Whisper is not live.** The transcript appears after the call ends (matches F4 AC1: "attached within a few minutes"), so the in-call screen has no live transcript panel like the mock's static one.
- Login throttling and the JWT secret fallback are per process. With several API workers set `JWT_SECRET` and move throttling to Redis.
- No self-service sign-up or "forgot password" e-mail: an admin creates users and resets passwords.
- Whisper runs in a FastAPI background task inside the API process — fine for one pilot team; move to a queue (RQ / Celery) if several long recordings run at once.
- Due dates are free text ("пятница"), not calendar dates.
- Not verified in the sandbox this was written in (no network): `npm install`, the LiveKit/Egress round trip and the FastAPI test suite. The drafting logic was run directly and all frontend files pass a syntax check — expect to fix small things on first run, most likely in the LiveKit/Egress setup.

## Troubleshooting

- **Call connects but nobody hears anything locally:** WebRTC through Docker on some hosts needs the UDP/TCP ports above reachable; `7881/tcp` is the fallback.
- **«Запись пока не началась»:** the `room_started` webhook did not reach the backend — check the webhook URL in `livekit.yaml` (see step 3) and `docker compose logs livekit egress`.
- **Egress finishes but the file is missing:** permissions on `data/recordings` (`chmod 777` for local dev).
- **First transcription is slow:** the model is downloading and loading; subsequent ones reuse it. Timing per audio minute is logged (`qadam.transcription`) — the same metric as the T4 benchmark.
