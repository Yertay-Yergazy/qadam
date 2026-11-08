"""The eval harness itself: matching, the "invented" rule (eval/README.md) and the CI gate."""
import json
from datetime import date

from app.services.drafting import DraftingResult, DraftProposal, SegmentIn
from app.services.transcription import TranscriptionResult
from eval.build_case import build_case
from eval.run_eval import INVENTED, MISS, draft_from_json, draft_to_json, load_cases, main, score_case

CASE = {
    "name": "case",
    "meeting_date": "2026-11-06",
    "people": ["Алия", "Ерлан"],
    "segments": [{"speaker": None, "text": "не важно, ответы подставляет фейковый drafter"}],
    "expected": [
        {"keywords": ["отчет", "excel"], "assignee": "Алия", "due_text": "пятница", "due_date": "2026-11-13"},
        {"title_contains": "документацию", "assignee": None, "due_text": None, "due_date": None},
    ],
}


class FakeDrafter:
    def __init__(self, *drafts: DraftProposal):
        self.drafts = list(drafts)

    def generate(self, segments, known_people, today=None):
        return DraftingResult(drafts=self.drafts)


def report_draft(**overrides) -> DraftProposal:
    fields = dict(title="Выгрузка отчёта в Excel", assignee_name="Алия", due_text="пятница", due_date=date(2026, 11, 13))
    return DraftProposal(**{**fields, **overrides})


def kinds(score) -> list[str]:
    return sorted(p.kind for p in score.problems)


def test_perfect_drafts_score_full_recall():
    score = score_case(CASE, FakeDrafter(report_draft(), DraftProposal(title="Обновить документацию")))
    assert (score.found, score.drafts, score.problems) == (2, 2, [])


def test_keywords_ignore_case_and_yo_and_word_order():
    score = score_case(CASE, FakeDrafter(report_draft(title="EXCEL: недельный ОТЧЁТ")))
    assert score.found == 1


def test_keywords_in_the_description_do_not_count():
    score = score_case(CASE, FakeDrafter(report_draft(title="Экспорт", description="Отчёт в Excel для руководителя")))
    assert score.found == 0


def test_missing_value_is_a_miss_not_an_invention():
    score = score_case(CASE, FakeDrafter(report_draft(assignee_name=None)))
    assert score.invented == 0 and MISS in kinds(score)


def test_wrong_value_is_invented():
    score = score_case(CASE, FakeDrafter(report_draft(assignee_name="Ерлан")))
    assert kinds(score).count(INVENTED) == 1


def test_value_where_key_says_none_is_invented():
    score = score_case(CASE, FakeDrafter(DraftProposal(title="Обновить документацию", due_text="завтра")))
    assert score.invented == 1


def test_extra_draft_is_invented():
    score = score_case(CASE, FakeDrafter(report_draft(), DraftProposal(title="Купить пиццу")))
    assert score.invented == 1 and score.drafts == 2


def test_gate_passes_for_the_rule_drafter():
    assert main([]) == 0


def test_gate_fails_on_miss_but_report_only_does_not(tmp_path):
    (tmp_path / "c.json").write_text(json.dumps(CASE, ensure_ascii=False), encoding="utf-8")
    assert main(["--meetings", str(tmp_path), "--drafter", "none"]) == 1
    out = tmp_path / "report.json"
    assert main(["--meetings", str(tmp_path), "--drafter", "none", "--report-only", "--json", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["totals"]["recall"] == 0 and report["cases"][0]["expected"] == 2


def test_empty_directory_fails(tmp_path):
    assert main(["--meetings", str(tmp_path)]) == 1


# ---------------------------------------------------------------- building a case from a recording
def test_build_case_turns_a_transcript_into_an_answer_key_skeleton(tmp_path):
    def fake_transcribe(path):
        segments = [SegmentIn(0.0, None, "Нужно починить логин."), SegmentIn(3.5, None, "Пусть Ерлан сделает.")]
        return TranscriptionResult(segments=segments, duration=61.4, language="ru")

    case = build_case(tmp_path / "standup.opus", ["Ерлан"], date(2026, 11, 6), fake_transcribe, source="https://example.org")
    assert case["name"] == "standup" and case["language"] == "ru" and case["duration_sec"] == 61
    assert case["segments"][1] == {"start_sec": 3.5, "speaker": None, "text": "Пусть Ерлан сделает."}
    assert case["expected"] == []

    (tmp_path / "standup.json").write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
    (loaded,) = load_cases(tmp_path)
    assert score_case(loaded, FakeDrafter()).expected == 0  # the skeleton is a valid eval case


def test_undated_due_wording_matches_by_containment():
    case = {**CASE, "expected": [{"keywords": ["отчет"], "assignee": None, "due_text": "до 1 апреля", "due_date": None}]}
    assert score_case(case, FakeDrafter(DraftProposal(title="Отчёт", due_text="1 апреля"))).problems == []
    wrong = score_case(case, FakeDrafter(DraftProposal(title="Отчёт", due_text="до 5 мая")))
    assert wrong.invented == 1


# ---------------------------------------------------------------- optional (debatable) items
OPTIONAL_CASE = {
    **CASE,
    "expected": [
        {"keywords": ["отчет"], "assignee": None, "due_text": None, "due_date": None},
        {"keywords": ["автотест"], "assignee": None, "due_text": None, "due_date": None, "optional": True},
    ],
}


def test_optional_item_found_is_neither_a_hit_nor_an_extra_draft():
    score = score_case(OPTIONAL_CASE, FakeDrafter(DraftProposal(title="Отчёт"), DraftProposal(title="Дописать автотест")))
    assert (score.expected, score.found, score.drafts, score.problems) == (1, 1, 1, [])


def test_optional_item_missing_is_not_a_miss():
    score = score_case(OPTIONAL_CASE, FakeDrafter(DraftProposal(title="Отчёт")))
    assert score.problems == []


def test_optional_item_with_an_invented_value_still_counts():
    score = score_case(OPTIONAL_CASE, FakeDrafter(DraftProposal(title="Отчёт"), DraftProposal(title="Автотест", assignee_name="Алия")))
    assert score.invented == 1


def test_required_item_gets_the_draft_before_an_optional_one():
    case = {**OPTIONAL_CASE, "expected": [{**OPTIONAL_CASE["expected"][1], "keywords": ["отчет"]}, OPTIONAL_CASE["expected"][0]]}
    score = score_case(case, FakeDrafter(DraftProposal(title="Отчёт")))
    assert (score.found, score.problems) == (1, [])


def test_keyword_alternatives():
    case = {**CASE, "expected": [{"keywords": ["отчет", ["excel", "эксел"]], "assignee": None, "due_text": None, "due_date": None}]}
    assert score_case(case, FakeDrafter(DraftProposal(title="Отчёт в Эксель"))).found == 1
    assert score_case(case, FakeDrafter(DraftProposal(title="Отчёт в Excel"))).found == 1
    assert score_case(case, FakeDrafter(DraftProposal(title="Отчёт в PDF"))).found == 0


def test_several_acceptable_values_for_an_ambiguous_owner():
    case = {**CASE, "expected": [{"keywords": ["отчет"], "assignee": ["Алия", None], "due_text": None, "due_date": None}]}
    for assignee in ("Алия", None):
        assert score_case(case, FakeDrafter(DraftProposal(title="Отчёт", assignee_name=assignee))).problems == []
    assert score_case(case, FakeDrafter(DraftProposal(title="Отчёт", assignee_name="Ерлан"))).invented == 1


# ---------------------------------------------------------------- matching by evidence (where it was said)
EVIDENCE_CASE = {
    **CASE,
    "segments": [
        {"speaker": None, "text": "Добрый день, начинаем планёрку отдела, всех рада видеть."},
        {"speaker": None, "text": "Сегодня до конца дня подготовьте пожалуйста служебную записку"},
        {"speaker": None, "text": "с полным анализом по всем подъездам на улице Ленина."},
        {"speaker": None, "text": "Теперь про погоду, обещают снег всю неделю и сильный ветер."},
    ],
    "expected": [
        {"keywords": ["служебн"], "segments": [[1, 2]], "assignee": None, "due_text": "до конца дня", "due_date": None}
    ],
}


def quoted(title, quote, **values):
    return DraftProposal(title=title, source_quote=quote, due_text="до конца дня", **values)


def test_reworded_title_counts_when_the_quote_comes_from_the_right_place():
    draft = quoted("Анализ подъездов на Ленина", "подготовьте пожалуйста служебную записку с полным анализом по всем подъездам")
    score = score_case(EVIDENCE_CASE, FakeDrafter(draft))
    assert (score.found, score.problems) == (1, [])


def test_quote_with_speaker_labels_is_still_located():
    draft = quoted("Анализ подъездов", "Алия: Сегодня до конца дня подготовьте пожалуйста служебную записку")
    assert score_case(EVIDENCE_CASE, FakeDrafter(draft)).found == 1


def test_draft_from_elsewhere_does_not_count():
    draft = quoted("Подготовиться к снегу", "Теперь про погоду, обещают снег всю неделю и сильный ветер.")
    score = score_case(EVIDENCE_CASE, FakeDrafter(draft))
    assert score.found == 0 and score.invented == 1


def test_junk_from_the_same_place_does_not_take_the_item_from_the_right_draft():
    junk = quoted("Полный день", "Сегодня до конца дня подготовьте пожалуйста служебную записку")
    right = quoted("Анализ подъездов на Ленина", "служебную записку с полным анализом по всем подъездам на улице Ленина")
    score = score_case(EVIDENCE_CASE, FakeDrafter(junk, right))
    assert score.found == 1
    assert [p.item for p in score.problems] == ["Полный день"]  # the junk one is the extra draft


# ---------------------------------------------------------------- saved predictions
def test_report_keeps_the_drafts_and_replay_rescores_them_without_the_drafter(tmp_path):
    meetings, out = tmp_path / "meetings", tmp_path / "out"
    meetings.mkdir(), out.mkdir()
    (meetings / "c.json").write_text(json.dumps(CASE, ensure_ascii=False), encoding="utf-8")
    first = out / "first.json"
    assert main(["--meetings", str(meetings), "--report-only", "--json", str(first)]) == 0  # rule drafter
    saved = json.loads(first.read_text(encoding="utf-8"))
    assert all("predictions" in c for c in saved["cases"])

    # Change the answer key, then re-score the very same drafts.
    (meetings / "c.json").write_text(json.dumps({**CASE, "expected": []}, ensure_ascii=False), encoding="utf-8")
    second = out / "second.json"
    assert main(["--meetings", str(meetings), "--replay", str(first), "--report-only", "--json", str(second)]) == 0
    replayed = json.loads(second.read_text(encoding="utf-8"))
    assert replayed["cases"][0]["predictions"] == saved["cases"][0]["predictions"]
    assert replayed["totals"]["expected"] == 0


def test_draft_json_round_trip():
    draft = DraftProposal(title="Отчёт", assignee_name="Алия", due_text="пятница", due_date=date(2026, 11, 13), acceptance_criteria=["А"])
    assert draft_from_json(json.loads(json.dumps(draft_to_json(draft)))) == draft


def test_replay_needs_drafts_for_every_case(tmp_path):
    (tmp_path / "c.json").write_text(json.dumps(CASE, ensure_ascii=False), encoding="utf-8")
    report = tmp_path / "r.json"
    report.write_text(json.dumps({"cases": []}), encoding="utf-8")
    assert main(["--meetings", str(tmp_path), "--replay", str(report)]) == 1
