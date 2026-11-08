from app.services.drafting import PlaceholderDrafter, SegmentIn

PEOPLE = ["Алия", "Ерлан", "Айгерим"]


def test_mock_meeting_gives_one_draft_and_skips_notifications():
    segs = [
        SegmentIn(4, "Алия", "Давайте в этот спринт добавим выгрузку недельного отчёта в Excel."),
        SegmentIn(6, "Ерлан", "Хорошо. Пусть сделает Айгерим, срок — пятница."),
        SegmentIn(7, "Айгерим", "Готово, когда руководитель скачивает файл. Внутри дата, статус и исполнитель."),
        SegmentIn(11, "Ерлан", "И когда-нибудь надо подумать про уведомления. Пока без решения."),
    ]
    result = PlaceholderDrafter().generate(segs, PEOPLE)
    assert len(result.drafts) == 1
    draft = result.drafts[0]
    assert draft.assignee_name == "Айгерим" and draft.due_text == "пятница"
    assert len(draft.acceptance_criteria) == 2
    assert result.skipped == ["уведомления"]


def test_never_invents_assignee_or_due_date():  # F5 AC2
    result = PlaceholderDrafter().generate([SegmentIn(0, None, "Нужно обновить документацию по API.")], PEOPLE)
    assert len(result.drafts) == 1
    assert result.drafts[0].assignee_name is None and result.drafts[0].due_text is None


# ---------------------------------------------------------------- case-aware names, dates (ST8)
from datetime import date  # noqa: E402

import pytest  # noqa: E402

FRI_NOV_6 = date(2026, 11, 6)  # a Friday


@pytest.mark.parametrize("phrase", ["Пусть Ерлан сделает", "Пусть Ерлану передадут", "Задачу возьмёт Ерлана команда", "Поручим это Ерлану"])
def test_russian_cases_of_a_name_are_matched(phrase):
    r = PlaceholderDrafter().generate([SegmentIn(0, None, f"Нужно починить логин. {phrase}.")], PEOPLE)
    assert r.drafts[0].assignee_name == "Ерлан"


def test_name_ending_in_a_is_matched_in_other_cases():
    r = PlaceholderDrafter().generate([SegmentIn(0, None, "Нужно собрать метрики. Пусть этим займётся Алии.")], PEOPLE)
    assert r.drafts[0].assignee_name == "Алия"


def test_unknown_person_is_not_assigned():
    r = PlaceholderDrafter().generate([SegmentIn(0, None, "Нужно собрать метрики. Пусть сделает Марат.")], PEOPLE)
    assert r.drafts[0].assignee_name is None


@pytest.mark.parametrize(
    "said,text,expected",
    [
        ("в пятницу", "пятница", date(2026, 11, 13)),  # today is Friday -> next Friday, not today
        ("к понедельнику", "понедельник", date(2026, 11, 9)),
        ("до среды", "среда", date(2026, 11, 11)),
        ("завтра", "завтра", date(2026, 11, 7)),
        ("на следующей неделе", "на следующей неделе", None),  # vague -> text kept, no invented date
    ],
)
def test_due_wording_becomes_a_date(said, text, expected):
    segs = [SegmentIn(0, None, f"Нужно выкатить релиз {said}.")]
    d = PlaceholderDrafter().generate(segs, PEOPLE, today=FRI_NOV_6).drafts[0]
    assert d.due_text == text and d.due_date == expected


def test_no_due_means_no_date():
    d = PlaceholderDrafter().generate([SegmentIn(0, None, "Нужно выкатить релиз.")], PEOPLE, today=FRI_NOV_6).drafts[0]
    assert d.due_text is None and d.due_date is None
