"""LLM drafter against a fake OpenAI-compatible server: the guards (F5 AC2), windows, fallback to rules."""
import json
from datetime import date

import httpx
import pytest

from app.services.drafting import RuleDrafter, SegmentIn, get_drafter
from app.services.llm_drafting import (
    LLMConfig,
    LLMDrafter,
    checked_assignee,
    checked_due,
    chunk_windows,
    cue_windows,
    grounded,
    merge_duplicates,
    refine_anchors,
    similar,
    substantive,
    task_scopes,
    transcript_lines,
)

PEOPLE = ["Алия", "Ерлан", "Айгерим"]
FRI_NOV_6 = date(2026, 11, 6)
MOCK_MEETING = [
    SegmentIn(4, "Алия", "Давайте в этот спринт добавим выгрузку недельного отчёта в Excel."),
    SegmentIn(6, "Ерлан", "Хорошо. Пусть сделает Айгерим, срок — пятница."),
    SegmentIn(7, "Айгерим", "Готово, когда руководитель скачивает файл. Внутри дата, статус и исполнитель."),
    SegmentIn(11, "Ерлан", "И когда-нибудь надо подумать про уведомления. Пока без решения."),
]


class FakeServer:
    """Answers each chat request with the next canned JSON object and records what it was asked."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        answer = self.answers.pop(0)
        content = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})

    def user_messages(self) -> list[str]:
        return [r["messages"][-1]["content"] for r in self.requests]


def drafter(server, mode="extract") -> LLMDrafter:
    return LLMDrafter(LLMConfig("http://llm/v1", "qwen", mode), transport=httpx.MockTransport(server))


def task(title, assignee=None, due=None, criteria=(), line=1):
    return {"line": line, "title": title, "acceptance_criteria": list(criteria), "assignee": assignee, "due": due}


# ---------------------------------------------------------------- guards
@pytest.mark.parametrize(
    "said,text,expected",
    [
        ("Айгерим", "Пусть сделает Айгерим.", "Айгерим"),
        ("Айгерим", "Поручим это Айгерим.", "Айгерим"),
        ("Ерлану", "Передадим Ерлану.", "Ерлан"),  # model may answer in another case
        ("Марат", "Пусть сделает Марат.", None),  # not a teammate
        ("Алия", "Пусть сделает Айгерим.", None),  # a teammate, but not named in the fragment
        (None, "Пусть сделает Айгерим.", None),
    ],
)
def test_assignee_must_be_a_teammate_named_in_the_fragment(said, text, expected):
    assert checked_assignee(said, text, PEOPLE) == expected


@pytest.mark.parametrize(
    "said,text,expected",
    [
        ("пятница", "Срок — пятница.", ("пятница", date(2026, 11, 13))),
        ("до пятницы", "Сделаем в пятницу.", ("пятница", date(2026, 11, 13))),  # reworded, same day
        ("завтра", "Сделаем в пятницу.", (None, None)),  # a date nobody said
        ("15 ноября", "Сдать до 15 ноября.", ("15 ноября", date(2026, 11, 15))),  # said verbatim, dated by rules
        ("16 ноября", "Сдать до 15 ноября.", (None, None)),
        (None, "Срок — пятница.", (None, None)),
    ],
)
def test_due_must_be_said_and_is_dated_by_rules(said, text, expected):
    assert checked_due(said, text, FRI_NOV_6) == expected


# ---------------------------------------------------------------- windows
def test_cue_windows_take_context_and_merge_neighbours():
    sentences = ["Привет всем.", "Погода хорошая.", "Нужно починить логин.", "Пусть Ерлан сделает.", "Обед.", "Кофе.", "Чай.", "Срок завтра."]
    assert cue_windows(sentences, PEOPLE, context=1, max_len=8) == [(1, 5), (6, 8)]


def test_cue_windows_cap_the_window_length():
    sentences = ["Нужно сделать задачу."] * 20
    assert all(end - start <= 8 for start, end in cue_windows(sentences, PEOPLE, context=1, max_len=8))


def test_chunk_windows_cover_everything():
    assert chunk_windows(25, size=12) == [(0, 12), (12, 24), (24, 25)]


def test_transcript_lines_drop_hedges_and_keep_speakers():
    bare, shown = transcript_lines(MOCK_MEETING)
    assert not any("когда-нибудь" in s for s in bare)
    assert shown[1] == "Ерлан: Хорошо." and bare[1] == "Хорошо."


@pytest.mark.parametrize(
    "claimed,expected",
    [
        ([1, 4], [(0, 3), (3, 5)]),  # a task owns the lines up to the next task
        ([4, 1], [(3, 5), (0, 3)]),  # order of the answer does not matter
        ([2, 2], [(1, 5), (1, 5)]),
        ([None, 9, 0, "1"], [None, None, None, None]),  # missing, out of range, not an int
        ([3, None], [(2, 5), None]),  # an invalid line is not an anchor
    ],
)
def test_task_scopes(claimed, expected):
    assert task_scopes(claimed, 5) == expected


@pytest.mark.parametrize(
    "criterion,ok",
    [("Руководитель скачивает файл", True), ("руководитель скачал файлы", True), ("Есть тёмная тема", False), ("", False)],
)
def test_criteria_must_be_grounded_in_the_text(criterion, ok):
    assert grounded(criterion, "Готово, когда руководитель скачивает файл.") is ok


# ---------------------------------------------------------------- extract mode
def test_extract_keeps_honest_values_and_drops_invented_ones():
    # window shown to the model: 1 Давайте…выгрузку, 2 Хорошо, 3 Пусть сделает Айгерим, срок — пятница, 4 Готово, когда…
    server = FakeServer(
        {
            "tasks": [
                task("выгрузка недельного отчёта в Excel.", "Айгерим", "пятница", ["Руководитель скачивает файл", "Есть PDF"]),
                task("Скачивание файла руководителем", "Айгерим", "пятница", line=None),  # no line -> no values
            ]
        }
    )
    result = drafter(server).generate(MOCK_MEETING, PEOPLE, today=FRI_NOV_6)

    report, other = result.drafts
    assert report.title == "Выгрузка недельного отчёта в Excel"
    assert (report.assignee_name, report.due_text, report.due_date) == ("Айгерим", "пятница", date(2026, 11, 13))
    assert report.acceptance_criteria == ["Руководитель скачивает файл"]  # the invented one is gone
    assert "Айгерим" in report.source_quote
    assert (other.assignee_name, other.due_text, other.due_date, other.acceptance_criteria) == (None, None, None, [])
    assert result.skipped == ["уведомления"]
    assert "Предложено задач: 2" in result.summary


def test_speaker_label_is_not_an_assignee():
    server = FakeServer({"tasks": [task("Выгрузка отчёта", assignee="Алия")]})  # "Алия: Давайте…" only speaks
    (draft,) = drafter(server).generate(MOCK_MEETING, PEOPLE).drafts
    assert draft.assignee_name is None


def test_owner_and_date_said_after_another_task_are_not_attached_to_it():
    # The m2 failure seen on Qwen3-1.7B: "Ерлан, завтра" from line 3 glued to the task on line 1.
    segs = [SegmentIn(0, None, "Нужно обновить документацию по API."), SegmentIn(1, None, "Надо починить логин. Пусть Ерлан сделает, завтра.")]
    server = FakeServer(
        {"tasks": [task("Обновить документацию", "Ерлан", "завтра", line=1), task("Починить логин", "Ерлан", "завтра", line=2)]}
    )
    docs, login = drafter(server).generate(segs, PEOPLE, today=FRI_NOV_6).drafts
    assert (docs.assignee_name, docs.due_text) == (None, None)
    assert (login.assignee_name, login.due_text) == ("Ерлан", "завтра")
    assert docs.source_quote == "Нужно обновить документацию по API."


def test_lines_are_numbered_in_the_prompt():
    server = FakeServer({"tasks": []})
    drafter(server).generate([SegmentIn(0, "Ерлан", "Нужно починить логин.")], PEOPLE)
    assert "1. Ерлан: Нужно починить логин." in server.user_messages()[0]


def test_extract_sends_only_cue_windows_with_participants():
    server = FakeServer({"tasks": []})
    segs = [SegmentIn(0, None, "Привет. Как дела. Погода. Нужно починить логин. Обед. Кофе. Чай. Пока.")]
    drafter(server).generate(segs, PEOPLE)
    (prompt,) = server.user_messages()
    assert "Участники: Алия, Ерлан, Айгерим" in prompt
    assert "починить логин" in prompt and "Привет" not in prompt


def test_extract_deduplicates_titles_and_skips_empty_ones():
    server = FakeServer({"tasks": [task("Починить логин"), task("починить  логин."), task("  ")]})
    result = drafter(server).generate([SegmentIn(0, None, "Нужно починить логин.")], PEOPLE)
    assert [d.title for d in result.drafts] == ["Починить логин"]


def test_no_candidates_means_no_calls():
    server = FakeServer()
    result = drafter(server).generate([SegmentIn(0, None, "Привет. Как дела.")], PEOPLE)
    assert result.drafts == [] and server.requests == []


def test_full_mode_reads_the_whole_transcript():
    server = FakeServer({"tasks": []})
    drafter(server, "full").generate([SegmentIn(0, None, "Привет. Как дела. Нужно починить логин.")], PEOPLE)
    assert "Привет" in server.user_messages()[0]


def test_request_asks_for_schema_constrained_json_without_thinking():
    server = FakeServer({"tasks": []})
    drafter(server).generate([SegmentIn(0, None, "Нужно починить логин.")], PEOPLE)
    (req,) = server.requests
    assert req["temperature"] == 0 and req["model"] == "qwen"
    assert req["response_format"]["type"] == "json_schema"
    assert req["response_format"]["json_schema"]["schema"]["required"] == ["tasks"]
    assert req["chat_template_kwargs"] == {"enable_thinking": False}
    assert [m["role"] for m in req["messages"]] == ["system", "user", "assistant", "user"]  # one-shot example


# ---------------------------------------------------------------- refine mode
def test_refine_drops_non_tasks_and_rewords_the_rest_keeping_rule_values():
    segs = [SegmentIn(0, None, "Нужно починить логин. Пусть Ерлан сделает завтра."), SegmentIn(1, None, "Надо бы выпить кофе.")]
    server = FakeServer(
        {"is_task": True, "title": "Исправить вход в систему", "acceptance_criteria": ["Логин починен", "Вход по отпечатку"]},
        {"is_task": False, "title": "Кофе", "acceptance_criteria": []},
    )
    result = drafter(server, "refine").generate(segs, PEOPLE, today=FRI_NOV_6)
    (draft,) = result.drafts
    assert draft.title == "Исправить вход в систему"
    assert (draft.assignee_name, draft.due_text) == ("Ерлан", "завтра")  # from the rules, untouched
    assert draft.acceptance_criteria == ["Логин починен"]  # the ungrounded one is dropped


def test_refine_keeps_verbatim_criteria_found_by_rules():
    server = FakeServer({"is_task": True, "title": "Выгрузка отчёта", "acceptance_criteria": ["Что-то придуманное"]})
    (draft,) = drafter(server, "refine").generate(MOCK_MEETING, PEOPLE).drafts
    assert draft.acceptance_criteria == RuleDrafter().generate(MOCK_MEETING, PEOPLE).drafts[0].acceptance_criteria


# ---------------------------------------------------------------- failures fall back to the rules
def _down(request):
    raise httpx.ConnectError("connection refused", request=request)


@pytest.mark.parametrize(
    "transport",
    [
        httpx.MockTransport(_down),
        httpx.MockTransport(lambda r: httpx.Response(500, text="model crashed")),
        httpx.MockTransport(FakeServer("not json at all")),
        httpx.MockTransport(FakeServer("[1, 2]")),
        httpx.MockTransport(lambda r: httpx.Response(200, json={"unexpected": True})),
    ],
    ids=["down", "http-500", "broken-json", "not-an-object", "wrong-shape"],
)
@pytest.mark.parametrize("mode", ["refine", "extract", "full"])
def test_any_llm_failure_falls_back_to_rules(transport, mode):
    result = LLMDrafter(LLMConfig("http://llm/v1", "qwen", mode), transport=transport).generate(MOCK_MEETING, PEOPLE)
    expected = RuleDrafter().generate(MOCK_MEETING, PEOPLE)
    assert [d.title for d in result.drafts] == [d.title for d in expected.drafts]
    assert result.summary == expected.summary


# ---------------------------------------------------------------- wiring
def test_drafter_llm_setting_builds_the_llm_drafter():
    assert isinstance(get_drafter("llm"), LLMDrafter)


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        LLMConfig("http://llm/v1", "qwen", "magic")


# ---------------------------------------------------------------- duplicates and invented tasks
@pytest.mark.parametrize(
    "a,b,same",
    [
        ("Добавить выгрузку недельного отчёта в Excel", "Выгрузка недельного отчёта в Excel", True),
        ("Починить логин", "починить  логин.", True),
        ("Починить логин", "Обновить документацию", False),
        ("API", "api", True),  # no content words: compared as text
        ("Өңдеу", "өңдеу.", True),  # Kazakh letters are part of words (without them nothing is left to compare)
    ],
)
def test_similar_titles(a, b, same):
    assert similar(a, b) is same


def test_merge_duplicates_keeps_the_earliest_mention_and_fills_gaps():
    # Seen on Qwen3-1.7B: the task listed at the proposal (line 1) and again at the assignment (line 3).
    tasks = [
        task("Выгрузка недельного отчёта", line=3, criteria=["Файл скачивается"]),
        task("Добавить выгрузку недельного отчёта", "Айгерим", None, line=1),
        task("Обновить логотип", line=4),
    ]
    first, logo = merge_duplicates(tasks)
    assert (first["line"], first["assignee"], first["acceptance_criteria"]) == (1, "Айгерим", ["Файл скачивается"])
    assert logo["title"] == "Обновить логотип"


def test_duplicate_does_not_steal_the_owner_line():
    server = FakeServer(
        {"tasks": [task("Добавить выгрузку недельного отчёта", "Айгерим", "пятница", line=1), task("Выгрузка недельного отчёта", line=3)]}
    )
    (draft,) = drafter(server).generate(MOCK_MEETING, PEOPLE, today=FRI_NOV_6).drafts
    assert (draft.assignee_name, draft.due_text) == ("Айгерим", "пятница")


def test_task_nobody_talked_about_is_dropped():
    server = FakeServer({"tasks": [task("Починить логин"), task("Купить пиццу для команды", line=1)]})
    result = drafter(server).generate([SegmentIn(0, None, "Нужно починить логин.")], PEOPLE)
    assert [d.title for d in result.drafts] == ["Починить логин"]


# ---------------------------------------------------------------- prompt language follows the meeting
@pytest.mark.parametrize(
    "text,language",
    [
        ("We need to fix the flaky login test.", "en"),
        ("Нужно починить логин.", "ru"),
        ("Есепті дайындау керек.", "ru"),  # Kazakh is Cyrillic: Russian prompt, Kazakh titles
        ("Нужно обновить API docs в README.", "ru"),  # Russian with a few English terms
    ],
)
def test_prompt_language_follows_the_fragment(text, language):
    server = FakeServer({"tasks": []})
    drafter(server, "full").generate([SegmentIn(0, None, text)], PEOPLE)  # full: every text reaches the model
    system = server.requests[0]["messages"][0]["content"]
    assert system.startswith("You list the tasks") is (language == "en")
    assert server.user_messages()[0].startswith("Participants:" if language == "en" else "Участники:")


# ---------------------------------------------------------------- Whisper fragments become sentences
def test_whisper_fragments_are_joined_into_sentences():
    # Real Whisper output (r3): segments end at pauses, mid-sentence.
    segs = [
        SegmentIn(0, None, "В принципе, что про бэкапы надо бы сказать, чтобы сейчас"),
        SegmentIn(4, None, "бэкапы на моей учётной записи делаются, надо бы будет"),
        SegmentIn(8, None, "наверное, на Мишу эту учётку переключить."),
    ]
    bare, _ = transcript_lines(segs)
    assert bare == [
        "В принципе, что про бэкапы надо бы сказать, чтобы сейчас бэкапы на моей учётной записи делаются, "
        "надо бы будет наверное, на Мишу эту учётку переключить."
    ]


def test_speaker_change_starts_a_new_utterance():
    segs = [SegmentIn(0, "Алия", "Нужно починить"), SegmentIn(1, "Алия", "логин."), SegmentIn(2, "Ерлан", "Беру.")]
    _, shown = transcript_lines(segs)
    assert shown == ["Алия: Нужно починить логин.", "Ерлан: Беру."]


def test_same_lines_seen_in_two_overlapping_windows_give_one_draft(caplog):
    # 14 cue sentences -> two windows (max 12) that overlap; the model words the shared task differently each time.
    sentences = [f"Нужно обновить документацию по разделу {i}." for i in range(14)]
    windows = cue_windows(sentences, PEOPLE)
    assert len(windows) == 2 and windows[1][0] < windows[0][1]
    shared_line_in_second = 10 - windows[1][0] + 1  # sentence 10 is in both windows
    # Both titles are grounded and not "similar" by words, so only the shared lines tell they are one task.
    server = FakeServer(
        {"tasks": [task("Обновить документацию раздела", line=11)]},
        {"tasks": [task("Раздел документации поправить", line=shared_line_in_second)]},
    )
    with caplog.at_level("DEBUG", logger="qadam.llm"):
        result = drafter(server).generate([SegmentIn(0, None, " ".join(sentences))], PEOPLE)
    assert [d.title for d in result.drafts] == ["Обновить документацию раздела"]
    assert "stands on the lines of an earlier draft" in caplog.text


# ---------------------------------------------------------------- anchors and criteria (seen on the live s1 example)
S1_LINES = [
    "Так, по релизу.",
    "Нужно обновить документацию по API.",
    "Это возьмёт Алия, до среды.",
    "Ок.",
    "Ещё надо поправить падение на странице оплаты.",
    "Да, это Айгерим, сегодня.",
    "Принято.",
]


def test_anchor_moves_back_to_the_line_where_the_task_was_said():
    # Qwen3-1.7B pointed at line 6 (the owner line) for the payment task.
    tasks = [task("Обновить документацию по API", line=2), task("Поправить падение на странице оплаты", line=6)]
    assert [t["line"] for t in refine_anchors(tasks, S1_LINES)] == [2, 5]


def test_anchor_never_moves_forward_or_past_the_previous_task():
    tasks = [task("Обновить документацию по API", line=1), task("Обновить документацию по API ещё раз", line=3)]
    assert [t["line"] for t in refine_anchors(tasks, S1_LINES)] == [1, 2]  # second may go back to 2, not to 1


def test_bad_line_numbers_are_left_alone():
    assert refine_anchors([task("Что-то", line=None)], S1_LINES)[0]["line"] is None


@pytest.mark.parametrize(
    "criterion,ok",
    [("До среды", False), ("Алия", False), ("by Friday", False), ("Оплата проходит с телефона", True), ("Файл скачивается до пятницы", True)],
)
def test_deadline_or_name_alone_is_not_a_criterion(criterion, ok):
    assert substantive(criterion, PEOPLE) is ok


def test_live_s1_answer_gives_clean_drafts():
    server = FakeServer(  # the raw answer Qwen3-1.7B gave on s1 (both defects in it)
        {
            "tasks": [
                task("Обновить документацию по API", "Алия", "до среды", ["До среды"], line=2),
                task("Поправить падение на странице оплаты", "Айгерим", "сегодня", line=6),
            ]
        }
    )
    segs = [
        SegmentIn(0, "Ерлан", "Так, по релизу. Нужно обновить документацию по API."),
        SegmentIn(1, "Ерлан", "Это возьмёт Алия, до среды."),
        SegmentIn(2, "Алия", "Ок. Ещё надо поправить падение на странице оплаты."),
        SegmentIn(3, "Ерлан", "Да, это Айгерим, сегодня."),
        SegmentIn(4, "Айгерим", "Принято."),
    ]
    docs, payment = drafter(server).generate(segs, PEOPLE, today=date(2026, 11, 4)).drafts
    assert docs.acceptance_criteria == []
    assert "падение" not in docs.source_quote  # the next task's words are no longer in this quote
    assert payment.source_quote.startswith("Алия: Ещё надо поправить падение")
    assert (payment.assignee_name, payment.due_text) == ("Айгерим", "сегодня")
