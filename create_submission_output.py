"""Create normalized submission_output.json from the queue's JSON results."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "data" / "submit_queue_output.json"
DEFAULT_OUTPUT = ROOT / "data" / "submission_output.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    source = json.loads(args.input.read_text(encoding="utf-8"))
    records = source.get("records") if isinstance(source, dict) else None
    if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
        raise ValueError(f"Expected a 'records' array of objects in {args.input}.")
    for index, record in enumerate(records, start=1):
        if not record.get("alpha_id") or record.get("outcome") not in {"active", "failed", "skipped"}:
            raise ValueError(f"Queue result {index} is missing alpha_id or a valid outcome.")

    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": str(args.input),
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Created {args.output} with {len(records)} result(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
