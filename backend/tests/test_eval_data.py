"""The committed answer keys are well-formed: a typo in an annotation silently skews every benchmark."""
import json
from datetime import date
from pathlib import Path

import pytest

EVAL_DIR = Path(__file__).resolve().parent.parent / "eval"
CASES = sorted(p for folder in ("meetings", "synthetic", "real") for p in (EVAL_DIR / folder).glob("*.json"))


def _values(value) -> list:
    return value if isinstance(value, list) else [value]


def test_all_data_sets_are_present():
    folders = {p.parent.name for p in CASES}
    assert folders == {"meetings", "synthetic", "real"}


@pytest.mark.parametrize("path", CASES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_answer_key_is_well_formed(path):
    case = json.loads(path.read_text(encoding="utf-8"))
    date.fromisoformat(case["meeting_date"])
    people, segments = case["people"], case["segments"]
    assert segments and all(isinstance(s["text"], str) for s in segments)

    for item in case["expected"]:
        assert item.get("keywords") or item.get("title_contains"), item
        assert all(a is None or a in people for a in _values(item.get("assignee"))), f"assignee not in people: {item}"
        for due in _values(item.get("due_date")):
            if due is not None:
                date.fromisoformat(due)
        if item.get("due_date") is not None:
            assert item.get("due_text"), f"a date without its wording: {item}"
        for start, end in item.get("segments", []):
            assert 0 <= start <= end < len(segments), f"segments {start}-{end} outside the transcript: {item}"
        if path.parent.name == "real":
            assert item.get("segments"), f"real meetings need evidence segments: {item}"
