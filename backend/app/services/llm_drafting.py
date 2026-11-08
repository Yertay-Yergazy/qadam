"""LLM drafter: a small self-hosted model behind an OpenAI-compatible API (llama.cpp `llama-server`, Ollama /v1).

The model only reads and words things. The code keeps it honest (F5 AC2):
  * an assignee counts only if it is one of `known_people` and is named in the text the model was shown;
  * a due wording counts only if it occurs in that text; the date is recomputed by the rules, never taken from the model;
  * the source quote is cut from the transcript by us, the model never writes it.
Any failure (server down, timeout, broken JSON) falls back to the rule drafter, so a meeting never loses its drafts.

Modes (LLM_MODE), cheapest first:
  refine  - rules find the drafts; the model drops false positives and rewrites title + criteria.
  extract - rules only point at candidate sentences (cue words, names, dates); the model extracts tasks around them.
  full    - the model reads the whole transcript in chunks. A baseline: slow on one CPU core.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Optional, Sequence

import httpx

from ..config import get_settings
from .drafting import (
    DraftingResult,
    DraftProposal,
    RuleDrafter,
    SegmentIn,
    all_dues,
    capitalize,
    find_person,
    is_action_cue,
    is_hedge,
    name_pattern,
    parse_due,
    split_sentences,
    summarize,
)
from .llm_prompts import (
    EXTRACT_SCHEMA,
    MAX_CRITERIA,
    MAX_CRITERION,
    MAX_TASKS_PER_WINDOW,
    MAX_TITLE,
    REFINE_SCHEMA,
    prompts_for,
)

log = logging.getLogger("qadam.llm")

MODES = ("refine", "extract", "full")
MAX_QUOTE = 300
MIN_TITLE_GROUNDING = 0.5  # share of a title's words that must have been said in the window


# ---------------------------------------------------------------- transport
class LLMError(RuntimeError):
    pass


class ChatClient:
    """Minimal OpenAI-compatible chat client that asks for JSON matching a schema (grammar-constrained decoding)."""

    def __init__(self, http: httpx.Client, model: str, max_tokens: int):
        self._http, self._model, self._max_tokens = http, model, max_tokens
        self.calls = 0

    def ask(self, system: str, example: tuple[str, dict], user: str, schema: dict) -> dict:
        example_q, example_a = example
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": example_q},
                {"role": "assistant", "content": json.dumps(example_a, ensure_ascii=False)},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "max_tokens": self._max_tokens,
            "response_format": {"type": "json_schema", "json_schema": {"name": "answer", "strict": True, "schema": schema}},
            "chat_template_kwargs": {"enable_thinking": False},  # Qwen3: no <think> block; ignored elsewhere
        }
        self.calls += 1
        try:
            response = self._http.post("/chat/completions", json=payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            answer = json.loads(content)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError(f"{exc.__class__.__name__}: {exc}") from exc
        if not isinstance(answer, dict):
            raise LLMError(f"expected a JSON object, got {content[:100]!r}")
        return answer


# ---------------------------------------------------------------- guards against invented values (F5 AC2)
def _norm(text: str) -> str:
    return " ".join((text or "").lower().replace("ё", "е").split())


def checked_assignee(name: Optional[str], text: str, people: Sequence[str]) -> Optional[str]:
    """The canonical teammate name, only if the model's name is a teammate AND that teammate is named in `text`."""
    person = find_person(name or "", people)
    return person if person and name_pattern(person).search(text) else None


def checked_due(wording: Optional[str], text: str, today: Optional[date]) -> tuple[Optional[str], Optional[date]]:
    """A due date only if it was said in `text`; normalised and dated by the rules, never by the model.

    Known wordings are compared after normalisation ('до пятницы' == 'в пятницу'); anything else must be verbatim.
    """
    if not wording:
        return None, None
    parsed = parse_due(wording, today)
    if parsed:
        return parsed if parsed[0] in {said for said, _ in all_dues(text, today)} else (None, None)
    return (wording.strip(), None) if _norm(wording) in _norm(text) else (None, None)


def _stems(text: str) -> set[str]:
    return {w[:4] for w in re.findall(r"[a-zа-яәғқңөұүһі0-9]+", _norm(text)) if len(w) > 3}


def grounded(phrase: str, text: str, share: float = 0.6) -> bool:
    """At least `share` of the phrase's content words occur in `text` (by stem). Small models invent criteria and
    whole tasks; a title may be reworded, so it is checked with a lower share than a criterion."""
    words = _stems(phrase)
    return bool(words) and len(words & _stems(text)) / len(words) >= share


def similar(a: str, b: str, share: float = 0.75) -> bool:
    """Two titles name the same task: most stems of the shorter one occur in the longer one."""
    x, y = _stems(a), _stems(b)
    if not x or not y:
        return _norm(a) == _norm(b)
    return len(x & y) / min(len(x), len(y)) >= share


def merge_duplicates(tasks: Sequence[dict]) -> list[dict]:
    """Small models often list one task twice: where it is proposed and where it is assigned. Keep the earliest
    mention as the anchor (so the owner line stays inside its scope) and fill its gaps from the twin."""
    def line(task: dict) -> int:
        return task["line"] if isinstance(task.get("line"), int) else 10**6

    merged: list[dict] = []
    for task in sorted(tasks, key=line):
        twin = next((m for m in merged if similar(m.get("title", ""), task.get("title", ""))), None)
        if twin is None:
            merged.append(dict(task))
            continue
        for key in ("assignee", "due"):
            twin[key] = twin.get(key) or task.get(key)
        twin["acceptance_criteria"] = [*(twin.get("acceptance_criteria") or []), *(task.get("acceptance_criteria") or [])]
    return merged


def task_scopes(claimed: Sequence[Optional[int]], count: int) -> list[Optional[tuple[int, int]]]:
    """Which lines of a window belong to each task: from the line the model points at up to the next task's line.

    `claimed` are 1-based line numbers from the model, the result 0-based [start, end) ranges (None for a bad number).
    The same rule as the rule drafter's "пусть сделает X" applying to the latest proposal: an owner or a date said
    after task B can never be attached to an earlier task A.
    """
    valid = [n if isinstance(n, int) and 1 <= n <= count else None for n in claimed]
    anchors = sorted({n for n in valid if n})
    scopes: list[Optional[tuple[int, int]]] = []
    for n in valid:
        following = next((a for a in anchors if a > n), count + 1) if n else None
        scopes.append((n - 1, following - 1) if n else None)
    return scopes


def refine_anchors(tasks: Sequence[dict], lines: Sequence[str]) -> list[dict]:
    """Move each task's `line` back to the line that matches its title best.

    Small models often point at the line where the owner was named ("Да, это Айгерим, сегодня") instead of the line
    where the task was said; the task's scope then misses its own words and the previous task swallows them.
    Only backwards (owners and dates follow the task) and never onto or before the previous task's line.
    Expects `tasks` sorted by line, as `merge_duplicates` returns them.
    """
    refined, previous = [], 0
    for task in tasks:
        n = task.get("line")
        if not (isinstance(n, int) and 1 <= n <= len(lines)):
            refined.append(task)
            continue
        title = _stems(task.get("title", ""))
        best, best_overlap = n, len(title & _stems(lines[n - 1]))
        for k in range(n - 1, previous, -1):
            overlap = len(title & _stems(lines[k - 1]))
            if overlap > best_overlap:
                best, best_overlap = k, overlap
        refined.append({**task, "line": best})
        previous = best
    return refined


def substantive(criterion: str, people: Sequence[str]) -> bool:
    """A criterion that is only a deadline or a name ("До среды", "Алия") is not a definition of done."""
    words = _stems(criterion)
    for said, _ in all_dues(criterion):
        words -= _stems(said)
    words -= {stem for person in people for stem in _stems(person)}
    return bool(words)


def _clean_title(title: str) -> str:
    return capitalize(" ".join((title or "").split()).strip(" .!?,;—-")[:MAX_TITLE])


def _clean_criteria(items: Sequence[str]) -> list[str]:
    cleaned = (capitalize(" ".join(str(c).split()).strip(" .")[:MAX_CRITERION]) for c in items or [])
    return list(dict.fromkeys(c for c in cleaned if c))[:MAX_CRITERIA]


# ---------------------------------------------------------------- which parts of the transcript the model sees
def utterances(segments: Sequence[SegmentIn]) -> list[tuple[Optional[str], str]]:
    """Consecutive segments of the same speaker joined into one text.

    Whisper cuts speech by pauses, not by sentences: "...бэкапы делаются, надо бы будет" / "наверное, на Мишу...".
    Splitting those fragments into "sentences" gave the model half-thoughts; joining first restores whole sentences.
    A call recording has no speaker labels at all, so the whole transcript becomes one utterance.
    """
    joined: list[tuple[Optional[str], str]] = []
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        if joined and joined[-1][0] == seg.speaker:
            joined[-1] = (seg.speaker, f"{joined[-1][1]} {text}")
        else:
            joined.append((seg.speaker, text))
    return joined


def transcript_lines(segments: Sequence[SegmentIn]) -> tuple[list[str], list[str]]:
    """Sentences without hedged ones, plus the same sentences as shown to the model ('Айгерим: Беру.').

    Every sentence keeps its speaker, so a window cut mid-utterance still says who is talking. Cues are looked for
    in the bare sentence, otherwise every labelled line would count as "names a teammate".
    """
    bare, shown = [], []
    for speaker, text in utterances(segments):
        for sentence in split_sentences(text):
            if is_hedge(sentence):
                continue
            bare.append(sentence)
            shown.append(f"{speaker}: {sentence}" if speaker else sentence)
    return bare, shown


def cue_windows(sentences: Sequence[str], people: Sequence[str], context: int = 2, max_len: int = 12) -> list[tuple[int, int]]:
    """[start, end) ranges around sentences that look like an action item; overlapping or touching ranges merge."""
    windows: list[list[int]] = []
    for i, sentence in enumerate(sentences):
        if not is_action_cue(sentence, people):
            continue
        start, end = max(0, i - context), min(len(sentences), i + context + 1)
        if windows and start <= windows[-1][1] and end - windows[-1][0] <= max_len:
            windows[-1][1] = max(windows[-1][1], end)
        else:
            windows.append([start, end])
    return [(a, b) for a, b in windows]


def chunk_windows(count: int, size: int = 12) -> list[tuple[int, int]]:
    return [(i, min(count, i + size)) for i in range(0, count, size)]


# ---------------------------------------------------------------- the drafter
@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    model: str
    mode: str = "extract"
    timeout_sec: float = 120
    max_tokens: int = 400

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError(f"LLM_MODE must be one of {MODES}, got {self.mode!r}")


class LLMDrafter:
    def __init__(self, config: LLMConfig, transport: httpx.BaseTransport | None = None):
        self.config = config
        self._transport = transport  # tests inject httpx.MockTransport
        self._rules = RuleDrafter()

    @classmethod
    def from_settings(cls) -> "LLMDrafter":
        s = get_settings()
        return cls(LLMConfig(s.llm_base_url, s.llm_model, s.llm_mode, s.llm_timeout_sec, s.llm_max_tokens))

    def generate(
        self, segments: Sequence[SegmentIn], known_people: Sequence[str], today: Optional[date] = None
    ) -> DraftingResult:
        rules = self._rules.generate(segments, known_people, today)
        started = time.perf_counter()
        http = httpx.Client(base_url=self.config.base_url.rstrip("/"), timeout=self.config.timeout_sec, transport=self._transport)
        client = ChatClient(http, self.config.model, self.config.max_tokens)
        try:
            if self.config.mode == "refine":
                drafts = self._refine(client, rules.drafts, known_people)
            else:
                drafts = self._extract(client, segments, known_people, today)
        except LLMError as exc:
            log.warning("LLM drafter failed (%s), using the rule drafter instead", exc)
            return rules
        finally:
            http.close()
        log.info("LLM drafter (%s): %d drafts, %d calls, %.1fs", self.config.mode, len(drafts), client.calls, time.perf_counter() - started)
        # Hedged topics are a rule-level judgement; the LLM modes keep them.
        return DraftingResult(summary=summarize(drafts), drafts=drafts, skipped=rules.skipped)

    def _refine(self, client: ChatClient, candidates: Sequence[DraftProposal], people: Sequence[str]) -> list[DraftProposal]:
        kept = []
        for draft in candidates:
            fragment = " ".join(dict.fromkeys([draft.description, *draft.acceptance_criteria, draft.source_quote]))
            prompts = prompts_for(fragment)
            answer = client.ask(prompts.refine_system, prompts.refine_example, prompts.refine_user(fragment), REFINE_SCHEMA)
            if not answer.get("is_task"):
                continue
            draft.title = _clean_title(answer.get("title", "")) or draft.title
            if not draft.acceptance_criteria:  # criteria the rules found are verbatim; keep them
                criteria = _clean_criteria(answer.get("acceptance_criteria"))
                draft.acceptance_criteria = [c for c in criteria if grounded(c, fragment) and substantive(c, people)]
            kept.append(draft)
        return kept

    def _extract(
        self, client: ChatClient, segments: Sequence[SegmentIn], people: Sequence[str], today: Optional[date]
    ) -> list[DraftProposal]:
        sentences, shown = transcript_lines(segments)
        if self.config.mode == "full":
            windows = chunk_windows(len(sentences))
        else:
            windows = cue_windows(sentences, people)

        drafts: list[DraftProposal] = []
        spans: list[range] = []  # sentences each accepted draft stands on (its own lines), parallel to `drafts`
        for start, end in windows:
            numbered = "\n".join(f"{i}. {line}" for i, line in enumerate(shown[start:end], 1))
            prompts = prompts_for(numbered)
            user = prompts.extract_user(people, numbered)
            answer = client.ask(prompts.extract_system, prompts.extract_example, user, EXTRACT_SCHEMA)
            raw = [t for t in (answer.get("tasks") or [])[:MAX_TASKS_PER_WINDOW] if isinstance(t, dict)]
            log.debug("window %d-%d: %d tasks %s", start, end, len(raw), [t.get("title") for t in raw])
            tasks = refine_anchors(merge_duplicates(raw), sentences[start:end])
            scopes = task_scopes([t.get("line") for t in tasks], end - start)
            for task, scope in zip(tasks, scopes):
                # Guards look at what was said in the task's own lines, not at speaker labels: proposing a task does
                # not make you its owner. No valid line -> nothing to check values against -> none are kept.
                own = slice(start + scope[0], start + scope[1]) if scope else slice(0, 0)
                said = " ".join(sentences[own])
                quote = shown[own] if scope else shown[start:end]
                title = _clean_title(task.get("title", ""))
                if not grounded(title, " ".join(sentences[start:end]), share=MIN_TITLE_GROUNDING):
                    log.debug("dropped, title not grounded in the window: %r", title)
                    continue  # a task nobody talked about
                if any(similar(title, d.title) for d in drafts):
                    log.debug("dropped, duplicate of an earlier draft: %r", title)
                    continue  # already found in an overlapping window
                if scope and any(start + scope[0] in span for span in spans):
                    # Overlapping windows show the same sentence twice; the model then words the same task anew.
                    log.debug("dropped, stands on the lines of an earlier draft: %r", title)
                    continue
                spans.append(range(own.start, own.stop))
                due_text, due_date = checked_due(task.get("due"), said, today)
                drafts.append(
                    DraftProposal(
                        title=title,
                        acceptance_criteria=[
                            c for c in _clean_criteria(task.get("acceptance_criteria")) if grounded(c, said) and substantive(c, people)
                        ],
                        assignee_name=checked_assignee(task.get("assignee"), said, people),
                        due_text=due_text,
                        due_date=due_date,
                        source_quote=" ".join(quote)[:MAX_QUOTE],
                    )
                )
        return drafts
