"""Review and submit Alpha IDs one at a time, saving structured outcomes."""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from auth import WQSession
from submit import get_alpha, show_summary, submit_alpha

ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "data" / "submit_queue_output.json"


def load_ids_from_file(path: str) -> list[str]:
    source = Path(path)
    content = source.read_text(encoding="utf-8")
    if source.suffix.lower() == ".json":
        values = json.loads(content)
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError(f"Expected a JSON array of Alpha ID strings in {source}.")
        return [value.strip() for value in values if value.strip()]
    return [line.strip() for line in content.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def write_queue_output(records: list[dict[str, Any]], output_path: Path = DEFAULT_OUTPUT) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "records": records,
    }
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _failed_record(alpha_id: str, message: str) -> dict[str, Any]:
    return {
        "alpha_id": alpha_id,
        "outcome": "failed",
        "brain_status": None,
        "attempts": 0,
        "message": message,
        "failed_checks": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", help="File containing Alpha IDs (JSON array or one ID per line).")
    parser.add_argument("--yes-all", action="store_true",
                        help="Submit eligible queue items without per-alpha prompts.")
    parser.add_argument("alpha_ids", nargs="*", help="Alpha IDs to process directly.")
    args = parser.parse_args()

    if args.file and args.alpha_ids:
        parser.error("Provide either --file or positional Alpha IDs, not both.")
    if args.file:
        alpha_ids = load_ids_from_file(args.file)
    else:
        alpha_ids = args.alpha_ids

    if not alpha_ids:
        print("No alpha IDs to process.")
        write_queue_output([])
        return 0

    print(f"Queue: {len(alpha_ids)} alpha(s) — {', '.join(alpha_ids)}\n")
    records: list[dict[str, Any]] = []
    session = WQSession()
    try:
        session.login()
    except Exception as exc:
        records = [_failed_record(alpha_id, f"Could not log in: {exc}") for alpha_id in alpha_ids]
        write_queue_output(records)
        print(f"Could not log in; recorded {len(records)} failed queue item(s).")
        return 1

    for index, alpha_id in enumerate(alpha_ids):
        print(f"\n{'#' * 60}\n# [{index + 1}/{len(alpha_ids)}] {alpha_id}\n{'#' * 60}")
        try:
            alpha = get_alpha(session.session, alpha_id)
        except Exception as exc:
            print(f"Could not fetch {alpha_id}: {exc} — recording as failed.")
            records.append(_failed_record(alpha_id, f"Could not fetch alpha: {exc}"))
            continue

        show_summary(alpha)
        brain_status = str(alpha.get("status") or "UNKNOWN")
        checks = (alpha.get("is") or {}).get("checks", []) or []
        failed_self_corr = [
            check for check in checks
            if check.get("name") == "SELF_CORRELATION" and check.get("result") == "FAIL"
        ]

        if brain_status == "ACTIVE":
            print(f"{alpha_id} is already ACTIVE; no new submission request sent.")
            records.append({
                "alpha_id": alpha_id,
                "outcome": "active",
                "brain_status": brain_status,
                "attempts": 0,
                "message": "Already ACTIVE before this queue run; no new request sent.",
                "failed_checks": [],
            })
            continue

        if args.yes_all and failed_self_corr:
            print(f"Skipping {alpha_id}: SELF_CORRELATION already fails before submission.")
            records.append({
                "alpha_id": alpha_id,
                "outcome": "failed",
                "brain_status": brain_status,
                "attempts": 0,
                "message": "Auto-submit skipped because SELF_CORRELATION already fails.",
                "failed_checks": failed_self_corr,
            })
            continue

        if args.yes_all and brain_status != "UNSUBMITTED":
            print(f"Skipping {alpha_id}: existing BRAIN status is {brain_status}; no duplicate request sent.")
            records.append({
                "alpha_id": alpha_id,
                "outcome": "skipped",
                "brain_status": brain_status,
                "attempts": 0,
                "message": "Auto-submit only sends new requests for UNSUBMITTED alphas.",
                "failed_checks": [],
            })
            continue

        if args.yes_all:
            print("Auto-submit enabled; submitting this eligible alpha without a prompt.")
            choice = "yes"
        else:
            try:
                choice = input(
                    f"\n[{index + 1}/{len(alpha_ids)}] Type 'yes' to submit {alpha_id}, "
                    "'skip' to move to the next one, or 'stop' to end the queue here: "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = "stop"

        if choice == "stop":
            print("Stopping queue — remaining alphas were not processed.")
            for remaining_id in alpha_ids[index:]:
                records.append({
                    "alpha_id": remaining_id,
                    "outcome": "skipped",
                    "brain_status": None,
                    "attempts": 0,
                    "message": "Not processed because the queue was stopped.",
                    "failed_checks": [],
                })
            break
        if choice != "yes":
            print(f"Skipped {alpha_id}.")
            records.append({
                "alpha_id": alpha_id,
                "outcome": "skipped",
                "brain_status": brain_status,
                "attempts": 0,
                "message": "User skipped this alpha.",
                "failed_checks": [],
            })
            continue

        try:
            records.append(submit_alpha(session.session, alpha_id))
        except Exception as exc:
            print(f"Error submitting {alpha_id}: {exc}")
            records.append(_failed_record(alpha_id, str(exc)))

        if index < len(alpha_ids) - 1:
            time.sleep(3)

    write_queue_output(records)
    active = [record for record in records if record.get("outcome") == "active"]
    failed = [record for record in records if record.get("outcome") == "failed"]
    skipped = [record for record in records if record.get("outcome") == "skipped"]

    print(f"\n{'=' * 60}\nQUEUE COMPLETE\n{'=' * 60}")
    print(f"Active:  {[record['alpha_id'] for record in active] if active else 'none'}")
    print(f"Failed:  {[record['alpha_id'] for record in failed] if failed else 'none'}")
    print(f"Skipped: {[record['alpha_id'] for record in skipped] if skipped else 'none'}")
    print(f"Structured queue output saved to {DEFAULT_OUTPUT.relative_to(ROOT)}.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
