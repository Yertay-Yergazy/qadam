# Drafter evaluation (ST7 answer key, ST10 run)

`python eval/run_eval.py` runs the configured drafter on every `eval/meetings/*.json` and compares it with the
answer key stored in the same file (`expected`). Exit code 1 if a target is missed (used by CI).

## Targets
* **Recall ≥ 80 %** — share of expected action items for which a draft with the right title fragment was produced.
* **Invented = 0**

## Rule "invented" (ST7)
A value is *invented* when the drafter outputs something the answer key does not contain:
1. a draft whose assignee is not the expected one (including any assignee where the key says `null`);
2. a draft whose `due_text` / `due_date` differs from the key (including any date where the key says `null`);
3. a draft that matches no expected item (a hallucinated task).
A missing value (`null` where the key has one) is a *miss* (hurts recall of the field), not an invention —
"не указан" is always the safe answer (F5 AC2).

## Adding the real T3 meetings
Copy `meetings/m1_sprint_planning.json`, paste the transcript segments, fill `expected` by hand from the recording
(not from the drafter's output), and commit the file. `meeting_date` is the reference for weekday → date.
