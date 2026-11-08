"""NLP step: transcript -> draft tasks.

This module defines the contract the rest of the app depends on (`DraftGenerator`), the deterministic
`RuleDrafter` (regex, ru + en) and the text helpers both drafters share. `get_drafter()` picks one by the
DRAFTER setting: `placeholder` (rules), `llm` (self-hosted model, see llm_drafting.py) or `none`.

Contract rules (A2, F5):
  * AC1: one draft per clearly stated action item.
  * AC2: never invent an assignee or a due date -> leave `assignee_name` / `due_text` as None.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional, Protocol, Sequence


@dataclass
class SegmentIn:
    start_sec: float
    speaker: Optional[str]
    text: str


@dataclass
class DraftProposal:
    title: str
    description: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    assignee_name: Optional[str] = None  # must be one of `known_people` or None
    due_text: Optional[str] = None  # human wording, normalised ('пятница'), None = not specified
    due_date: Optional[date] = None  # resolved calendar date, None if the wording is vague
    source_quote: str = ""


@dataclass
class DraftingResult:
    summary: str = ""
    drafts: list[DraftProposal] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # topics discussed but not decided


class DraftGenerator(Protocol):
    def generate(
        self, segments: Sequence[SegmentIn], known_people: Sequence[str], today: Optional[date] = None
    ) -> DraftingResult: ...


class NoopDrafter:
    def generate(self, segments, known_people, today=None) -> DraftingResult:
        return DraftingResult()


# ---------------------------------------------------------------- placeholder (regex, ru + en)
_PROPOSE = re.compile(r"\b(давайте|надо|нужно|необходимо|добавим|сделаем|let\x27s|we need to|we should)\b", re.I)
_OWNER = re.compile(r"\b(сделает|возьмёт|возьмет|займётся|займется|пусть|поручим|назначим|will do|will take)\b", re.I)
_HEDGE = re.compile(r"когда-нибудь|без решения|потом решим|someday|maybe|not decided", re.I)
_DONE_WHEN = re.compile(r"^(?:готово|done|принято)[,:]?\s*(?:когда|when)\s+(.*)$", re.I)
_TOPIC = re.compile(r"\b(?:про|about)\s+(.+?)[.!?]*$", re.I)
_DUE = re.compile(
    r"\b(сегодня|завтра|послезавтра|понедельник\w*|вторник\w*|сред[уаыой]\w*|четверг\w*|пятниц\w*|суббот\w*"
    r"|воскресень\w*|на следующей неделе|до конца (?:недели|месяца)|today|tomorrow|next week"
    r"|(?:next )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b",
    re.I,
)
# (stem regex, canonical nominative, weekday index Mon=0). Handles cases: в пятницу, к пятнице, до пятницы...
_WEEKDAYS = [
    (r"^понедельник", "понедельник", 0), (r"^вторник", "вторник", 1), (r"^сред", "среда", 2),
    (r"^четверг", "четверг", 3), (r"^пятниц", "пятница", 4), (r"^суббот", "суббота", 5), (r"^воскресень", "воскресенье", 6),
    (r"^monday", "monday", 0), (r"^tuesday", "tuesday", 1), (r"^wednesday", "wednesday", 2),
    (r"^thursday", "thursday", 3), (r"^friday", "friday", 4), (r"^saturday", "saturday", 5), (r"^sunday", "sunday", 6),
]


def normalise_due(raw: str, today: Optional[date] = None) -> tuple[str, Optional[date]]:
    """'в пятницу' -> ('пятница', next Friday). Vague phrases keep their text and get no date (never guess)."""
    word = raw.lower().strip()
    today = today or date.today()
    if word in ("сегодня", "today"):
        return word, today
    if word in ("завтра", "tomorrow"):
        return word, today + timedelta(days=1)
    if word == "послезавтра":
        return word, today + timedelta(days=2)
    day = word.removeprefix("next ")  # "next friday" is a weekday, "next week" stays vague
    for stem, canonical, idx in _WEEKDAYS:
        if re.match(stem, day):
            ahead = (idx - today.weekday()) % 7 or 7  # a weekday named today means next week
            return canonical, today + timedelta(days=ahead)
    return word, None


def parse_due(text: str, today: Optional[date] = None) -> Optional[tuple[str, Optional[date]]]:
    """The first due wording in `text`, normalised: 'сделать к пятнице' -> ('пятница', date). None if there is none."""
    m = _DUE.search(text or "")
    return normalise_due(m.group(1), today) if m else None


def all_dues(text: str, today: Optional[date] = None) -> list[tuple[str, Optional[date]]]:
    """Every due wording in `text`, normalised."""
    return [normalise_due(m.group(1), today) for m in _DUE.finditer(text or "")]


def resolve_due_text(text: str, today: Optional[date] = None) -> Optional[date]:
    """Used when a reviewer edits the free-text due field: recompute the date, or None if not parseable."""
    due = parse_due(text, today)
    return due[1] if due else None


def is_hedge(sentence: str) -> bool:
    """'когда-нибудь', 'потом решим': discussed, not decided -> never a task."""
    return bool(_HEDGE.search(sentence))


def is_action_cue(sentence: str, people: Sequence[str]) -> bool:
    """Loose pre-filter: the sentence proposes, assigns, names a deadline or a teammate."""
    return bool(
        _PROPOSE.search(sentence) or _OWNER.search(sentence) or _DUE.search(sentence) or find_person(sentence, people)
    )


def summarize(drafts: Sequence[DraftProposal]) -> str:
    if not drafts:
        return ""
    parts = []
    for d in drafts:
        extra = ", ".join(
            x for x in (d.assignee_name and f"исполнитель — {d.assignee_name}", d.due_text and f"срок — {d.due_text}") if x
        )
        parts.append(f"«{d.title}»" + (f" ({extra})" if extra else ""))
    return f"Предложено задач: {len(drafts)}. " + "; ".join(parts) + "."


def capitalize(s: str) -> str:
    return s[:1].upper() + s[1:]


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def _title(sentence: str) -> str:
    t = re.sub(r"\bв этот спринт\b", "", sentence, flags=re.I)
    t = re.sub(r"\s{2,}", " ", t).strip()
    t = re.sub(r"^(?:и|а|ну|тогда)\s+", "", t, flags=re.I)
    t = re.sub(r"^(?:давайте|надо|нужно|необходимо|let\x27s|we need to|we should)\s+", "", t, flags=re.I)
    return capitalize(t.strip(" .!?,;—-"))


def name_pattern(name: str) -> re.Pattern:
    """Matches a name in any Russian case: Ерлан / Ерлана / Ерлану / Ерланом; Алия / Алии / Алию / Алией."""
    stem = name[:-1] if name[-1].lower() in "аяйь" and len(name) > 3 else name
    return re.compile(r"(?<![\w])" + re.escape(stem) + r"[а-яёәғқңөұүһіa-z]{0,3}(?![\w])", re.I)


def find_person(sentence: str, people: Sequence[str]) -> Optional[str]:
    """Only a person who is actually named in the sentence and is in `known_people`; otherwise None (F5 AC2)."""
    best: tuple[int, str] | None = None
    for name in people:
        m = name_pattern(name).search(sentence)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), name)
    return best[1] if best else None


class RuleDrafter:
    """Rule-based drafter (ru + a bit of en): case-aware names, weekday -> date. No network, deterministic."""

    def generate(
        self, segments: Sequence[SegmentIn], known_people: Sequence[str], today: Optional[date] = None
    ) -> DraftingResult:
        result = DraftingResult()
        current: Optional[DraftProposal] = None

        def apply_attrs(draft: DraftProposal, sentence: str) -> None:
            person = find_person(sentence, known_people)
            due = parse_due(sentence, today)
            if person:
                draft.assignee_name = person
                draft.source_quote = sentence
            if due:
                draft.due_text, draft.due_date = due
                draft.source_quote = sentence

        for seg in segments:
            collecting_criteria = False
            for sent in split_sentences(seg.text):
                if _HEDGE.search(sent):
                    topic = _TOPIC.search(sent)
                    if topic:
                        result.skipped.append(topic.group(1).strip())
                    current, collecting_criteria = None, False
                    continue
                done_when = _DONE_WHEN.match(sent)
                if done_when and current:
                    current.acceptance_criteria.append(capitalize(done_when.group(1).strip()))
                    collecting_criteria = True
                    continue
                if collecting_criteria and current:
                    current.acceptance_criteria.append(capitalize(sent))
                    continue
                if _PROPOSE.search(sent) and not _OWNER.search(sent):
                    current = DraftProposal(title=_title(sent), description=sent, source_quote=sent)
                    apply_attrs(current, sent)
                    result.drafts.append(current)
                elif _OWNER.search(sent) and current:
                    apply_attrs(current, sent)

        result.summary = summarize(result.drafts)
        return result


PlaceholderDrafter = RuleDrafter  # backwards-compatible alias


def get_drafter(kind: str) -> DraftGenerator:
    if kind == "none":
        return NoopDrafter()
    if kind == "llm":
        from .llm_drafting import LLMDrafter  # imports this module; also keeps httpx out of the rule-only path

        return LLMDrafter.from_settings()
    return RuleDrafter()
