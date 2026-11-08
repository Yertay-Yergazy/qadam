"""Turn a meeting recording into an eval case: transcribe it exactly like production, leave `expected` empty.

    python eval/build_case.py audio.opus --out eval/local/m10_sales.json \
        --people "Анна,Иван" --date 2022-06-17 --source https://youtu.be/...

Fill `expected` by hand afterwards (see eval/README.md). Whisper runs with WHISPER_MODEL=base by default, the
model of the dev stand, so the drafter is scored on the same recognition errors it sees in production.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def build_case(
    audio: Path,
    people: Sequence[str],
    meeting_date: date,
    transcribe: Callable,
    name: str | None = None,
    source: str = "",
) -> dict:
    result = transcribe(audio)
    return {
        "name": name or audio.stem,
        "source": source,
        "language": result.language,
        "duration_sec": round(result.duration),
        "meeting_date": meeting_date.isoformat(),
        "people": list(people),
        "segments": [{"start_sec": s.start_sec, "speaker": s.speaker, "text": s.text} for s in result.segments],
        "expected": [],
    }


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--people", default="", help="comma-separated participant names as they appear in the meeting")
    ap.add_argument("--date", type=date.fromisoformat, required=True, help="meeting date (reference for weekdays)")
    ap.add_argument("--source", default="", help="where the recording comes from (URL)")
    ap.add_argument("--name", help="case name, default: file name")
    ap.add_argument("--whisper-model", default="base", help="default: base, as on the dev stand")
    args = ap.parse_args(argv)

    os.environ["WHISPER_MODEL"] = args.whisper_model  # before the settings are first read
    from app.services.transcription import transcribe_file

    people = [p.strip() for p in args.people.split(",") if p.strip()]
    case = build_case(args.audio, people, args.date, transcribe_file, name=args.name, source=args.source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{args.out}: {len(case['segments'])} segments, {case['duration_sec']}s, language={case['language']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
