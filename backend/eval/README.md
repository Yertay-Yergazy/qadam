# Drafter evaluation (ST7 answer key, ST10 run)

`python eval/run_eval.py` runs the configured drafter on every `eval/meetings/*.json` and compares it with the
answer key stored in the same file (`expected`). Exit code 1 if a target is missed (used by CI).

```bash
python eval/run_eval.py                                  # CI gate: eval/meetings, rule drafter
python eval/run_eval.py --drafter llm                    # same gate, another drafter (DRAFTER values)
python eval/run_eval.py --meetings eval/local --report-only --json report.json   # benchmark, never fails
```

The report prints recall, precision (matched drafts / all drafts), invented values and the time the drafter took.

## Targets
* **Recall ≥ 80 %** — share of expected action items for which a matching draft was produced.
* **Invented = 0**

## Rule "invented" (ST7)
A value is *invented* when the drafter outputs something the answer key does not contain:
1. a draft whose assignee is not the expected one (including any assignee where the key says `null`);
2. a draft whose `due_text` / `due_date` differs from the key (including any date where the key says `null`);
3. a draft that matches no expected item (a hallucinated task).
A missing value (`null` where the key has one) is a *miss* (hurts recall of the field), not an invention —
"не указан" is always the safe answer (F5 AC2).

## What counts as an action item (annotation rules)
Annotate from **our** transcript (`eval/build_case.py`, Whisper `base`), not from YouTube captions or the video:
the drafter only ever sees that text, recognition errors included.
* An action item is a **new action agreed on in the meeting**: "Иван, подготовь отчёт к пятнице", "let's open an issue
  for that", "I'll update the invite" said as the outcome of a discussion.
* **Not** an action item: a status report or a personal plan that only retells ongoing work ("на этой неделе я
  занимаюсь интеграцией", "I'll be working on the design issue"), announcements, ideas without a decision.
* **Debatable** items get `"optional": true`: personal plans with a concrete deliverable ("дописать автотест"),
  meeting logistics ("остаться после дейли и обсудить"). A reviewer could accept them, so a draft for one is neither
  a hit nor an extra draft, and no draft is not a miss. A value the drafter attaches to it is still checked: an invented
  assignee or date counts.
* `assignee` — a person from `people` who is **named** as the owner in the transcript. "Я возьму" / "I'll do it" with no
  name stays `null`: call recordings have no speaker labels, so nobody can know who "I" is. Organisations
  ("министерству … поручаю") are not users either: `null`.
* `due_text` / `due_date` — only a deadline that was said. Words the rules can date get the date (`пятница`,
  `tomorrow`); others are kept as text with `due_date: null` ("в недельный срок", "до 1 апреля", "end of the milestone").

## Matching a draft to an expected item
Two passes, required items before optional ones:
1. **Keywords** — `"keywords": ["отчет", ["excel", "эксел"]]`: every entry must occur in the draft's title (case and
   ё/е ignored); a list entry means "any of these". Use word stems. Only the title counts: a description may quote the
   transcript and would match anything. The older `"title_contains": "..."` is one keyword.
2. **Evidence** — for items still open: a draft whose quote comes from the item's `segments` and whose title shares
   the most words with what was said there. A reworded title then is a hit, not a miss plus an invented draft; a junk
   draft cut from the same spot does not take the item away from the right one.

A value may list alternatives when the transcript is genuinely ambiguous: `"assignee": ["Jose", null]`. A deadline the
rules cannot date matches by containment ("до 1 апреля" ≈ "1 апреля").

## Data sets
* `eval/meetings/` — small, clean regression set, committed, gates CI.
* `eval/synthetic/` — committed hard cases written by hand: several tasks in a row, self-assignment, a discussion
  without decisions, recognition-style run-ons, English, Kazakh. Report only (the rule drafter is not expected to pass).
* `eval/local/` — git-ignored. Meetings built from third-party recordings (e.g. YouTube) whose transcripts we may
  not redistribute. Same file format; run with `--meetings eval/local --report-only`.

Synthetic cases flatter a drafter: on clean one-sentence segments Qwen3-1.7B scored 100 %, on real Whisper output it
found a fraction of that. Decide on real recordings.

## Adding a meeting
From a recording (transcribed exactly like production, Whisper `base`):
```bash
python eval/build_case.py audio.opus --out eval/local/m10_sales.json --date 2022-06-17 --people "Анна,Иван"
```
Then fill `expected` by hand from the transcript (never from a drafter's output). Give every item `segments` (the
inclusive index ranges of the segments where it was said) so evidence matching works. `meeting_date` is the
reference for weekday → date.
