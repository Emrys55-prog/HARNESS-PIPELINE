"""Extract the selected Alpha IDs into a queue-ready JSON list."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "data" / "top25_alphas.json"
DEFAULT_OUTPUT = ROOT / "data" / "top25_alpha_ids.json"


def extract_ids(input_path: Path) -> list[str]:
    if not input_path.is_file():
        raise FileNotFoundError(f"Selected-alpha file not found: {input_path}")

    data = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("alphas"), list):
        raise ValueError("Expected a JSON object with an 'alphas' list.")

    alpha_ids: list[str] = []
    for index, alpha in enumerate(data["alphas"], start=1):
        if not isinstance(alpha, dict):
            raise ValueError(f"Alpha record {index} is not a JSON object.")
        alpha_id = str(alpha.get("id") or "").strip()
        if not alpha_id:
            raise ValueError(f"Alpha record {index} is missing its 'id'.")
        if alpha_id not in alpha_ids:
            alpha_ids.append(alpha_id)

    if not alpha_ids:
        raise ValueError("No Alpha IDs were found in the selected-alpha file.")
    return alpha_ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT,
                        help="Selected alpha records (default: data/top25_alphas.json)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="Output ID list (default: data/top25_alpha_ids.json)")
    args = parser.parse_args()

    alpha_ids = extract_ids(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(alpha_ids, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(alpha_ids)} Alpha ID(s) to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
