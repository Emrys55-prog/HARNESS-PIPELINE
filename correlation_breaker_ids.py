"""Select failed alphas with self-correlation below the Correlation Breaker threshold."""

import argparse
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "data" / "failed_submissions.json"
DEFAULT_OUTPUT = ROOT / "data" / "correlation_breaker_ids.json"
DEFAULT_THRESHOLD = 0.8


def self_correlation_value(record: dict[str, Any]) -> float | None:
    """Return the SELF_CORRELATION check value when it is a finite number."""
    checks = record.get("checks") or record.get("failed_checks") or []
    if not isinstance(checks, list):
        return None

    for check in checks:
        if not isinstance(check, dict) or str(check.get("name", "")).upper() != "SELF_CORRELATION":
            continue
        try:
            value = float(check.get("value"))
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help="Include SELF_CORRELATION values strictly below this number (default: 0.8).")
    args = parser.parse_args()

    if not math.isfinite(args.threshold):
        parser.error("--threshold must be a finite number.")

    records = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
        raise ValueError(f"Expected an array of failed submission records in {args.input}.")

    alpha_ids: list[str] = []
    for record in records:
        alpha_id = str(record.get("alpha_id") or "").strip()
        correlation = self_correlation_value(record)
        if alpha_id and correlation is not None and correlation < args.threshold and alpha_id not in alpha_ids:
            alpha_ids.append(alpha_id)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(alpha_ids, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(alpha_ids)} Alpha ID(s) with self-correlation below {args.threshold:g} to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
