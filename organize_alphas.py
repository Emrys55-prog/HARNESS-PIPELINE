
import json
import csv
import re
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent

import sys
sys.path.insert(0, str(BASE_DIR / "src"))
from harness_pipeline.fields import FieldCatalog

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
ALPHA_FILE = DATA_DIR / "fetched_alphas.json"
FIELD_CACHE = BASE_DIR / "data" / "field_cache" / "fields_USA_TOP3000_d1.json"

OUTPUT_JSON = BASE_DIR / "data" / "alphas_by_field.json"
OUTPUT_CSV = BASE_DIR / "data" / "alphas_by_field.csv"

# These are grouping/neutralization identifiers, not alpha input fields.
GROUPING_TOKENS = {
    "sector",
    "industry",
    "subindustry",
    "market",
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_field_names(field_data):
    """Extract field IDs from actual field metadata records."""
    names = set()

    def walk(obj):
        if isinstance(obj, dict):
            field_id = obj.get("id")

            # Actual field records have metadata such as dataset,
            # description, or type. Avoid nested category/dataset IDs.
            if isinstance(field_id, str) and (
                "dataset" in obj
                or "description" in obj
                or "type" in obj
            ):
                names.add(field_id)

            for value in obj.values():
                if isinstance(value, (dict, list)):
                    walk(value)

        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(field_data)
    return names


def extract_expression_fields(expression, known_fields):
    """Find field inputs in the expression, excluding group identifiers."""
    if not expression:
        return []

    tokens = set(
        re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", expression)
    )

    matched = tokens.intersection(known_fields)
    matched -= GROUPING_TOKENS

    return sorted(matched)


def get_metric(alpha, section, metric):
    return alpha.get(section, {}).get(metric)


def metric_value(record, metric):
    value = record.get(metric)
    return value if isinstance(value, (int, float)) else -999


def main():
    if not ALPHA_FILE.exists():
        print(f"Missing file: {ALPHA_FILE}")
        return

    try:
        catalog = FieldCatalog.load()
    except RuntimeError as exc:
        print(exc)
        return

    alphas = load_json(ALPHA_FILE)
    known_fields = set(catalog.metadata)

    grouped = defaultdict(list)
    no_field_matches = []

    for alpha_id, alpha in alphas.items():
        expression = alpha.get("regular", {}).get("code", "")

        fields = extract_expression_fields(expression, known_fields)

        record = {
            "id": alpha_id,
            "field": ", ".join(fields) if fields else "UNKNOWN",
            "fields": fields,
            "expression": expression,
            "grade": alpha.get("grade"),
            "status": alpha.get("status"),
            "neutralization": alpha.get("settings", {}).get(
                "neutralization"
            ),
            "decay": alpha.get("settings", {}).get("decay"),

            # In-sample metrics
            "is_sharpe": get_metric(alpha, "is", "sharpe"),
            "is_fitness": get_metric(alpha, "is", "fitness"),
            "is_turnover": get_metric(alpha, "is", "turnover"),
            "is_drawdown": get_metric(alpha, "is", "drawdown"),
            "is_returns": get_metric(alpha, "is", "returns"),
            "is_margin": get_metric(alpha, "is", "margin"),

            # Train metrics
            "train_sharpe": get_metric(alpha, "train", "sharpe"),
            "train_fitness": get_metric(alpha, "train", "fitness"),
            "train_turnover": get_metric(alpha, "train", "turnover"),

            # Test metrics
            "test_sharpe": get_metric(alpha, "test", "sharpe"),
            "test_fitness": get_metric(alpha, "test", "fitness"),
            "test_turnover": get_metric(alpha, "test", "turnover"),
        }

        if fields:
            # Group only by underlying input field(s).
            group_key = " + ".join(fields)
            grouped[group_key].append(record)
        else:
            no_field_matches.append(record)

    # Sort each group by Fitness first, then Sharpe.
    for records in grouped.values():
        records.sort(
            key=lambda x: (
                metric_value(x, "is_fitness"),
                metric_value(x, "is_sharpe"),
            ),
            reverse=True,
        )

    # Sort groups by number of alphas, largest first.
    sorted_groups = sorted(
        grouped.items(),
        key=lambda item: len(item[1]),
        reverse=True,
    )

    output = {
        "total_alphas": len(alphas),
        "field_groups": {
            field: {
                "count": len(records),
                "alphas": records,
            }
            for field, records in sorted_groups
        },
        "unmatched_alphas": no_field_matches,
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    # Flat CSV output
    all_records = []

    for _, records in sorted_groups:
        all_records.extend(records)

    all_records.extend(no_field_matches)

    if all_records:
        fieldnames = list(all_records[0].keys())

        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=fieldnames,
            )
            writer.writeheader()
            writer.writerows(all_records)

    print("\nOrganization complete.")
    print(f"Total alphas: {len(alphas)}")
    print(f"Known field IDs: {len(known_fields)}")
    print(f"Field groups: {len(grouped)}")
    print(f"Unmatched alphas: {len(no_field_matches)}")
    print(f"JSON: {OUTPUT_JSON}")
    print(f"CSV:  {OUTPUT_CSV}")

    print("\nLargest field groups:")
    for field, records in sorted_groups[:20]:
        print(f"{field}: {len(records)} alphas")

    if no_field_matches:
        print("\nUnmatched alpha IDs:")
        for record in no_field_matches:
            print(record["id"])


if __name__ == "__main__":
    main()
