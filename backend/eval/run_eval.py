"""Run the drafter against the answer key. Usage: python eval/run_eval.py [--min-recall 0.8]"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.drafting import SegmentIn, get_drafter  # noqa: E402


def evaluate(path: Path, drafter) -> tuple[int, int, list[str], int]:
    case = json.loads(path.read_text(encoding="utf-8"))
    segs = [SegmentIn(float(i), s.get("speaker"), s["text"]) for i, s in enumerate(case["segments"])]
    result = drafter.generate(segs, case["people"], today=date.fromisoformat(case["meeting_date"]))
    problems: list[str] = []
    found = 0
    unmatched = list(result.drafts)
    for exp in case["expected"]:
        hit = next((d for d in unmatched if exp["title_contains"].lower() in d.title.lower()), None)
        if not hit:
            problems.append(f"MISS      no draft for «{exp['title_contains']}»")
            continue
        unmatched.remove(hit)
        found += 1
        got = {"assignee": hit.assignee_name, "due_text": hit.due_text, "due_date": hit.due_date.isoformat() if hit.due_date else None}
        for field, got_v in got.items():
            want = exp.get(field)
            if got_v == want:
                continue
            kind = "MISS     " if got_v is None else "INVENTED "
            problems.append(f"{kind} «{exp['title_contains']}».{field}: expected {want!r}, got {got_v!r}")
    for d in unmatched:
        problems.append(f"INVENTED  extra draft «{d.title}»")
    invented = sum(p.startswith("INVENTED") for p in problems)
    return found, len(case["expected"]), problems, invented


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-recall", type=float, default=0.8)
    ap.add_argument("--drafter", default="placeholder")
    args = ap.parse_args()
    drafter = get_drafter(args.drafter)
    total_found = total = total_invented = 0
    for path in sorted((Path(__file__).parent / "meetings").glob("*.json")):
        found, n, problems, invented = evaluate(path, drafter)
        total_found, total, total_invented = total_found + found, total + n, total_invented + invented
        print(f"{path.name}: {found}/{n} items found, {invented} invented")
        for p in problems:
            print("   ", p)
    recall = total_found / total if total else 0.0
    print(f"\nRECALL {recall:.0%} (target ≥ {args.min_recall:.0%})   INVENTED {total_invented} (target 0)")
    return 0 if recall >= args.min_recall and total_invented == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
