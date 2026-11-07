"""Submit a full Alpha ID batch or refresh failed-alpha correlation checks."""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUTPUT_DIR = DATA / "pipeline_2"
DEFAULT_INPUT = DATA / "alpha_ids.txt"
TRIAL_OUTPUT = OUTPUT_DIR / "submit_queue_output.json"
STATUS_OUTPUT = OUTPUT_DIR / "status_check_output.json"
FAILED_IDS_OUTPUT = OUTPUT_DIR / "failed_ids_to_check.json"
COMBINED_OUTPUT = OUTPUT_DIR / "combined_queue_output.json"
NORMALIZED_OUTPUT = OUTPUT_DIR / "submission_output.json"
ACTIVE_OUTPUT = OUTPUT_DIR / "active_alphas.json"
FAILED_OUTPUT = OUTPUT_DIR / "failed_submissions.json"
BREAKER_IDS_OUTPUT = OUTPUT_DIR / "correlation_breaker_ids.json"


def run_stage(script: str, *args: str) -> int:
    command = [sys.executable, str(ROOT / script), *args]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def load_records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
        raise ValueError(f"Expected a records array in {path}.")
    return records


def save_queue_output(records: list[dict[str, Any]], path: Path) -> None:
    path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "records": records,
    }, indent=2) + "\n", encoding="utf-8")


def unique_failed_ids(records: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for record in records:
        alpha_id = str(record.get("alpha_id") or "").strip()
        if record.get("outcome") == "failed" and alpha_id and alpha_id not in ids:
            ids.append(alpha_id)
    return ids


def merge_refreshed_results(
    original: list[dict[str, Any]], refreshed: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {str(record.get("alpha_id")): record for record in refreshed if record.get("alpha_id")}
    return [
        by_id.get(str(record.get("alpha_id")), record)
        if record.get("outcome") == "failed" else record
        for record in original
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file", type=Path, default=DEFAULT_INPUT,
        help="Full batch of Alpha IDs for a new run (JSON array or one ID per line).",
    )
    parser.add_argument(
        "--threshold", type=float, default=0.8,
        help="Include failed alphas whose SELF_CORRELATION value is strictly below this (default: 0.8).",
    )
    parser.add_argument(
        "--correlation-timeout", type=float, default=900,
        help="Maximum seconds to wait on each failed alpha for a numeric self-correlation result.",
    )
    parser.add_argument(
        "--refresh-existing", action="store_true",
        help="Process only IDs in the existing failed report; does not rerun the full batch.",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.refresh_existing:
        if not FAILED_OUTPUT.exists():
            parser.error(f"No existing Pipeline 2 failed report found: {FAILED_OUTPUT}")
        original_failed = load_records(FAILED_OUTPUT)
        failed_ids = list(dict.fromkeys(
            str(record.get("alpha_id") or "").strip()
            for record in original_failed if str(record.get("alpha_id") or "").strip()
        ))
        if ACTIVE_OUTPUT.exists():
            original_records = load_records(ACTIVE_OUTPUT) + original_failed
        elif TRIAL_OUTPUT.exists():
            original_records = load_records(TRIAL_OUTPUT)
        else:
            original_records = original_failed
        trial_status = 0
        print(f"Processing {len(failed_ids)} failed alpha(s) only; each unresolved check will be triggered and awaited before the next alpha.")
    else:
        if not args.file.exists():
            parser.error(f"Alpha ID file does not exist: {args.file}")
        print(f"Pipeline 2: submitting the batch in {args.file}.")
        print(f"Pipeline 2 results will be saved under {OUTPUT_DIR}.")
        trial_status = run_stage(
            "submit_queue.py", "--file", str(args.file), "--yes-all", "--output", str(TRIAL_OUTPUT)
        )
        original_records = load_records(TRIAL_OUTPUT)
        failed_ids = unique_failed_ids(original_records)
        print(f"First pass complete. Triggering and awaiting correlation for {len(failed_ids)} failed alpha(s), one at a time.")

    FAILED_IDS_OUTPUT.write_text(json.dumps(failed_ids, indent=2) + "\n", encoding="utf-8")
    if failed_ids:
        status_status = run_stage(
            "submit_queue.py", "--file", str(FAILED_IDS_OUTPUT), "--yes-all",
            "--trigger-correlation", "--correlation-timeout", str(args.correlation_timeout),
            "--output", str(STATUS_OUTPUT),
        )
        refreshed_records = load_records(STATUS_OUTPUT)
    else:
        status_status = 0
        refreshed_records = []
        save_queue_output([], STATUS_OUTPUT)
        print("No failed alphas need a status refresh.")

    combined_records = merge_refreshed_results(original_records, refreshed_records)
    save_queue_output(combined_records, COMBINED_OUTPUT)

    stages = (
        ("create_submission_output.py", "--input", str(COMBINED_OUTPUT), "--output", str(NORMALIZED_OUTPUT)),
        ("filter_alphas.py", "--input", str(NORMALIZED_OUTPUT),
         "--active-output", str(ACTIVE_OUTPUT), "--failed-output", str(FAILED_OUTPUT)),
        ("correlation_breaker_ids.py", "--input", str(FAILED_OUTPUT),
         "--output", str(BREAKER_IDS_OUTPUT), "--threshold", str(args.threshold)),
    )
    for script, *stage_args in stages:
        result = run_stage(script, *stage_args)
        if result != 0:
            print(f"Pipeline 2 stopped: {script} failed with exit code {result}.", file=sys.stderr)
            return result

    print("Pipeline 2 complete.")
    print(f"Failed IDs checked: {FAILED_IDS_OUTPUT}")
    print(f"Updated failed report: {FAILED_OUTPUT}")
    print(f"Correlation Breaker IDs: {BREAKER_IDS_OUTPUT}")
    return status_status or trial_status


if __name__ == "__main__":
    raise SystemExit(main())
