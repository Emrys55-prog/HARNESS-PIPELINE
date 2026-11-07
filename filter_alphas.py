"""Split normalized submission results into ACTIVE and failed records."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "data" / "submission_output.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--active-output", type=Path, default=ROOT / "data" / "active_alphas.json")
    parser.add_argument("--failed-output", type=Path, default=ROOT / "data" / "failed_submissions.json")
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        raise ValueError(f"Expected a 'records' array in {args.input}.")

    active = [record for record in records if record.get("outcome") == "active"]
    failed = [record for record in records if record.get("outcome") == "failed"]
    args.active_output.parent.mkdir(parents=True, exist_ok=True)
    args.failed_output.parent.mkdir(parents=True, exist_ok=True)
    args.active_output.write_text(json.dumps(active, indent=2) + "\n", encoding="utf-8")
    args.failed_output.write_text(json.dumps(failed, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(active)} active alpha(s) to {args.active_output}.")
    print(f"Saved {len(failed)} failed submission(s) to {args.failed_output}.")
    print("Skipped entries remain in submission_output.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
