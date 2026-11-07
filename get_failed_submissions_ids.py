"""Extract failed Alpha IDs from failed_submissions.json."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "data" / "failed_submissions.json"
DEFAULT_OUTPUT = ROOT / "data" / "failed_id_submissions.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    records = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
        raise ValueError(f"Expected an array of failed submission records in {args.input}.")

    alpha_ids: list[str] = []
    for record in records:
        alpha_id = str(record.get("alpha_id") or "").strip()
        if alpha_id and alpha_id not in alpha_ids:
            alpha_ids.append(alpha_id)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(alpha_ids, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(alpha_ids)} failed Alpha ID(s) to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
