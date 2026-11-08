"""Score a drafter against hand-written answer keys (see eval/README.md).

    python eval/run_eval.py                                   # CI gate on eval/meetings
    python eval/run_eval.py --meetings eval/local --report-only --json out.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.drafting import DraftGenerator, DraftProposal, SegmentIn, get_drafter  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
MISS, INVENTED = "MISS", "INVENTED"


@dataclass
class Problem:
    kind: str  # MISS | INVENTED
    item: str  # which expected item / extra draft it is about
    detail: str

    def __str__(self) -> str:
        return f"{self.kind:<9} «{self.item}» {self.detail}"


@dataclass
class CaseScore:
    name: str
    expected: int
    found: int
    drafts: int
    seconds: float
    problems: list[Problem] = field(default_factory=list)
    predictions: list[dict] = field(default_factory=list)  # the drafts themselves, for --replay and error analysis

    @property
    def invented(self) -> int:
        return sum(p.kind == INVENTED for p in self.problems)


def draft_to_json(draft: DraftProposal) -> dict:
    data = asdict(draft)
    data["due_date"] = draft.due_date.isoformat() if draft.due_date else None
    return data


def draft_from_json(data: dict) -> DraftProposal:
    due = data.get("due_date")
    return DraftProposal(**{**data, "due_date": date.fromisoformat(due) if due else None})


def _norm(text: str | None) -> str:
    return (text or "").lower().replace("ё", "е")


def _keywords(item: dict) -> list[list[str]]:
    """Every entry must occur in the title; an entry that is a list is satisfied by any of its stems.

    ["отчет", ["excel", "эксел"]] = "отчет" AND ("excel" OR "эксел"). Stems survive an LLM rewording the title;
    `title_contains` is the old one-phrase form.
    """
    entries = item.get("keywords") or [item["title_contains"]]
    return [[_norm(k) for k in (e if isinstance(e, list) else [e])] for e in entries]


def _label(item: dict) -> str:
    return " ".join("|".join(alternatives) for alternatives in _keywords(item))


def _matches(draft: DraftProposal, keywords: Sequence[Sequence[str]]) -> bool:
    """Title only: it is what the reviewer reads, and a description may quote the transcript verbatim."""
    title = _norm(draft.title)
    return all(any(k in title for k in alternatives) for alternatives in keywords)


def _same(field: str, want: str | None | list, got: str | None) -> bool:
    """Exact, except a due wording the rules cannot date: 'до 1 апреля' and '1 апреля' are the same deadline.

    `want` may be a list of acceptable values when the transcript is genuinely ambiguous: ["Jose", null].
    """
    if isinstance(want, list):
        return any(_same(field, w, got) for w in want)
    if field == "due_text" and want and got:
        a, b = _norm(want).strip(), _norm(got).strip()
        return a in b or b in a
    return want == got


# ---------------------------------------------------------------- evidence: where in the transcript a draft comes from
_SHINGLE = 5  # words in a row that must match to say "this quote comes from here"


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zа-яәғқңөұүһі0-9]+", _norm(text))


def _stems(text: str) -> set[str]:
    return {w[:4] for w in _words(text) if len(w) > 3}


class Transcript:
    """Maps a draft's source quote back to the transcript segments it was cut from.

    The quote is matched by runs of words, so speaker labels ("Алия:") and skipped sentences inside it do no harm.
    """

    def __init__(self, segments: Sequence[dict]):
        self.texts = [s["text"] for s in segments]
        self.words: list[str] = []
        self.owner: list[int] = []  # segment index of every word
        for i, text in enumerate(self.texts):
            words = _words(text)
            self.words += words
            self.owner += [i] * len(words)
        self._index: dict[tuple[str, ...], list[int]] = {}
        for pos in range(len(self.words) - _SHINGLE + 1):
            self._index.setdefault(tuple(self.words[pos : pos + _SHINGLE]), []).append(pos)

    def locate(self, quote: str) -> set[int]:
        words = _words(quote)
        found: set[int] = set()
        for i in range(len(words) - _SHINGLE + 1):
            for pos in self._index.get(tuple(words[i : i + _SHINGLE]), []):
                found.update(self.owner[pos : pos + _SHINGLE])
        return found

    def text_of(self, indices: set[int]) -> str:
        return " ".join(self.texts[i] for i in sorted(indices) if 0 <= i < len(self.texts))


def _item_segments(item: dict) -> set[int]:
    """`"segments": [[340, 347], [400, 402]]`: inclusive ranges of the segments where the item was said."""
    return {i for start, end in item.get("segments") or [] for i in range(start, end + 1)}


def _evidence_match(item: dict, drafts: Sequence[DraftProposal], transcript: Transcript) -> DraftProposal | None:
    """A draft whose quote comes from where the item was said and whose title shares the most words with that place.

    The second rule keeps a junk draft cut from the same spot from taking the item away from the right one.
    """
    where = _item_segments(item)
    if not where:
        return None
    said = _stems(transcript.text_of(where))
    best, best_overlap = None, 0
    for draft in drafts:
        if transcript.locate(draft.source_quote) & where:
            overlap = len(_stems(draft.title) & said)
            if overlap > best_overlap:
                best, best_overlap = draft, overlap
    return best


# ---------------------------------------------------------------- scoring
def score_case(case: dict, drafter: DraftGenerator) -> CaseScore:
    segments = [SegmentIn(float(i), s.get("speaker"), s["text"]) for i, s in enumerate(case["segments"])]
    started = time.perf_counter()
    result = drafter.generate(segments, case["people"], today=date.fromisoformat(case["meeting_date"]))
    return score_drafts(case, result.drafts, time.perf_counter() - started)


def score_drafts(case: dict, drafts: Sequence[DraftProposal], seconds: float = 0.0) -> CaseScore:
    """Scoring alone: also used to re-score drafts saved in an earlier report (`--replay`) without the model."""
    required = [e for e in case["expected"] if not e.get("optional")]
    optional = [e for e in case["expected"] if e.get("optional")]
    score = CaseScore(case["name"], len(required), 0, len(drafts), seconds, predictions=[draft_to_json(d) for d in drafts])
    transcript = Transcript(case["segments"])
    unmatched = list(drafts)
    hits: dict[int, DraftProposal] = {}
    # Required items first, so an optional item never takes the draft a required one needs. Title keywords first,
    # then evidence for items still open: a reworded title must not count as a miss plus an invented draft.
    for match in (
        lambda e: next((d for d in unmatched if _matches(d, _keywords(e))), None),
        lambda e: _evidence_match(e, unmatched, transcript),
    ):
        for exp in required + optional:
            if id(exp) in hits:
                continue
            hit = match(exp)
            if hit:
                hits[id(exp)] = hit
                unmatched.remove(hit)

    for exp in required + optional:
        label = _label(exp)
        hit = hits.get(id(exp))
        if not hit:
            if not exp.get("optional"):
                score.problems.append(Problem(MISS, label, "no draft"))
            continue
        if exp.get("optional"):
            score.drafts -= 1  # neither found nor extra; a wrong value on it still counts as invented
        else:
            score.found += 1
        for problem in _value_problems(exp, hit, label):
            if problem.kind == INVENTED or not exp.get("optional"):
                score.problems.append(problem)
    for d in unmatched:
        score.problems.append(Problem(INVENTED, d.title, "extra draft"))
    return score


def _value_problems(exp: dict, draft: DraftProposal, label: str) -> list[Problem]:
    got = {
        "assignee": draft.assignee_name,
        "due_text": draft.due_text,
        "due_date": draft.due_date.isoformat() if draft.due_date else None,
    }
    problems = []
    for name, value in got.items():
        want = exp.get(name)
        if not _same(name, want, value):
            kind = MISS if value is None else INVENTED  # "не указан" is always safe (F5 AC2)
            problems.append(Problem(kind, label, f"{name}: expected {want!r}, got {value!r}"))
    return problems


def load_cases(directory: Path) -> list[dict]:
    cases = []
    for path in sorted(directory.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        case.setdefault("name", path.stem)
        cases.append(case)
    return cases


@dataclass
class Totals:
    expected: int
    found: int
    drafts: int
    invented: int
    seconds: float

    @property
    def recall(self) -> float:
        return self.found / self.expected if self.expected else 1.0

    @property
    def precision(self) -> float:
        return self.found / self.drafts if self.drafts else 1.0


def totals(scores: Sequence[CaseScore]) -> Totals:
    return Totals(
        expected=sum(s.expected for s in scores),
        found=sum(s.found for s in scores),
        drafts=sum(s.drafts for s in scores),
        invented=sum(s.invented for s in scores),
        seconds=sum(s.seconds for s in scores),
    )


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--meetings", type=Path, default=EVAL_DIR / "meetings", help="directory with *.json answer keys")
    ap.add_argument("--drafter", default="placeholder", help="same values as the DRAFTER setting")
    ap.add_argument("--min-recall", type=float, default=0.8)
    ap.add_argument("--report-only", action="store_true", help="always exit 0 (benchmarks, not the CI gate)")
    ap.add_argument("--json", type=Path, help="also write the full report here (scores and the drafts)")
    ap.add_argument("--replay", type=Path, help="re-score the drafts saved in an earlier --json report, no drafter")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a legacy code page

    cases = load_cases(args.meetings)
    if not cases:
        print(f"No answer keys in {args.meetings}")
        return 1
    if args.replay:
        saved = {c["name"]: c for c in json.loads(args.replay.read_text(encoding="utf-8"))["cases"]}
        missing = [c["name"] for c in cases if c["name"] not in saved]
        if missing:
            print(f"{args.replay} has no drafts for: {', '.join(missing)}")
            return 1
        scores = [
            score_drafts(case, [draft_from_json(d) for d in saved[case["name"]]["predictions"]], saved[case["name"]]["seconds"])
            for case in cases
        ]
    else:
        drafter = get_drafter(args.drafter)
        scores = [score_case(case, drafter) for case in cases]

    for s in scores:
        print(f"{s.name}: {s.found}/{s.expected} found, {s.drafts} drafts, {s.invented} invented, {s.seconds:.1f}s")
        for p in s.problems:
            print("   ", p)
    t = totals(scores)
    print(
        f"\nRECALL {t.recall:.0%} (target ≥ {args.min_recall:.0%})   PRECISION {t.precision:.0%}   "
        f"INVENTED {t.invented} (target 0)   TIME {t.seconds:.1f}s total, {t.seconds / len(scores):.1f}s per meeting"
    )

    if args.json:
        report = {
            "drafter": args.drafter,
            "totals": {**asdict(t), "recall": t.recall, "precision": t.precision},
            "cases": [{**asdict(s), "invented": s.invented} for s in scores],
        }
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    passed = t.recall >= args.min_recall and t.invented == 0
    return 0 if passed or args.report_only else 1


if __name__ == "__main__":
    sys.exit(main())
