"""Submit an existing Alpha ID batch and create correlation-breaker candidates."""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUTPUT_DIR = DATA / "pipeline_2"
DEFAULT_INPUT = DATA / "alpha_ids.txt"


def run_stage(script: str, *args: str) -> int:
    command = [sys.executable, str(ROOT / script), *args]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file", type=Path, default=DEFAULT_INPUT,
        help="Full batch of Alpha IDs (JSON array or one ID per line; default: data/alpha_ids.txt).",
    )
    parser.add_argument(
        "--threshold", type=float, default=0.8,
        help="Include failed alphas whose SELF_CORRELATION value is strictly below this (default: 0.8).",
    )
    args = parser.parse_args()

    if not args.file.exists():
        parser.error(f"Alpha ID file does not exist: {args.file}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    trial_output = OUTPUT_DIR / "submit_queue_output.json"
    queue_output = OUTPUT_DIR / "status_check_output.json"
    normalized_output = OUTPUT_DIR / "submission_output.json"
    active_output = OUTPUT_DIR / "active_alphas.json"
    failed_output = OUTPUT_DIR / "failed_submissions.json"
    breaker_ids_output = OUTPUT_DIR / "correlation_breaker_ids.json"

    print(f"Pipeline 2: submitting the batch in {args.file}.")
    print(f"Pipeline 2 results will be saved under {OUTPUT_DIR}.")
    trial_status = run_stage(
        "submit_queue.py", "--file", str(args.file), "--yes-all", "--output", str(trial_output)
    )
    print("First pass complete; refreshing BRAIN status and correlation checks without resubmitting.")
    status_status = run_stage(
        "submit_queue.py", "--file", str(args.file), "--check-only", "--output", str(queue_output)
    )

    stages = (
        ("create_submission_output.py", "--input", str(queue_output), "--output", str(normalized_output)),
        ("filter_alphas.py", "--input", str(normalized_output),
         "--active-output", str(active_output), "--failed-output", str(failed_output)),
        ("correlation_breaker_ids.py", "--input", str(failed_output),
         "--output", str(breaker_ids_output), "--threshold", str(args.threshold)),
    )
    for script, *stage_args in stages:
        result = run_stage(script, *stage_args)
        if result != 0:
            print(f"Pipeline 2 stopped: {script} failed with exit code {result}.", file=sys.stderr)
            return result

    print("Pipeline 2 complete.")
    print(f"Active report: {active_output}")
    print(f"Failed report: {failed_output}")
    print(f"Correlation Breaker IDs: {breaker_ids_output}")
    return status_status or trial_status


if __name__ == "__main__":
    raise SystemExit(main())
