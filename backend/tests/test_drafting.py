from app.services.drafting import PlaceholderDrafter, SegmentIn, normalise_due

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


@pytest.mark.parametrize(
    "phrase",
    ["Пусть Ерлан сделает", "Пусть Ерлану передадут", "Задачу возьмёт Ерлана команда", "Поручим это Ерлану", "Пусть сделает Ерланға"],
)
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


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("next week", ("next week", None)),  # was ("week", None)
        ("next friday", ("friday", date(2026, 11, 13))),
        ("Friday", ("friday", date(2026, 11, 13))),
        ("tomorrow", ("tomorrow", date(2026, 11, 7))),
    ],
)
def test_english_due_wording(raw, expected):
    assert normalise_due(raw, FRI_NOV_6) == expected


# ---------------------------------------------------------------- dictation format "СТ-N – ... Исполнитель – ... Дедлайн – ..."
def test_dictated_stories_become_drafts_with_assignee_and_date():
    segs = [
        SegmentIn(0, None, "СТ-16, выделение основных правил в отдельный модуль"),
        SegmentIn(4, None, "с модульными тестами – Unit Tests."),
        SegmentIn(6, None, "Исполнитель – Ерлан."),
        SegmentIn(15, None, "Оценка – 3 часа, осталось 3 часа."),
        SegmentIn(18, None, "Дедлайн – 12 ноября."),
        SegmentIn(44, None, "СТ-12 – отображение исходного предложения в каждом черновике."),
        SegmentIn(49, None, "Исполнитель – Марат."),  # not in the team -> must stay unassigned
        SegmentIn(59, None, "Дедлайн – 17 ноября."),
    ]
    r = PlaceholderDrafter().generate(segs, PEOPLE, today=date(2026, 11, 9))
    assert [d.title for d in r.drafts] == [
        "Выделение основных правил в отдельный модуль",
        "Отображение исходного предложения в каждом черновике",
    ]
    a, b = r.drafts
    assert a.assignee_name == "Ерлан" and a.due_date == date(2026, 11, 12) and a.due_text == "12 ноября"
    assert "Unit Tests" in a.description and "3 часа" in a.description
    assert b.assignee_name is None and "Марат" in b.description  # never assigned to an unknown name
    assert b.due_date == date(2026, 11, 17)
    assert r.summary.startswith("Предложено задач: 2")


def test_date_with_month_name_rolls_to_next_year_when_passed():
    from app.services.drafting import normalise_due
    assert normalise_due("12 ноября", date(2026, 11, 20))[1] == date(2027, 11, 12)
    assert normalise_due("31 февраля", date(2026, 1, 1))[1] is None  # impossible date -> no date, no crash
