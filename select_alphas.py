
import json
import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
INPUT_FILE = DATA_DIR / "alphas_by_field.json"
OUTPUT_JSON = BASE_DIR / "data" / "top25_alphas.json"
OUTPUT_CSV = BASE_DIR / "data" / "top25_alphas.csv"

TARGET_COUNT = 25
MAX_PER_FIELD_GROUP = 3


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def percentile_ranks(records, metric, lower_is_better=False):
    valid = []

    for record in records:
        value = record.get(metric)
        if isinstance(value, (int, float)):
            valid.append((record, value))

    valid.sort(key=lambda x: x[1], reverse=not lower_is_better)

    ranks = {}
    count = len(valid)

    for i, (record, _) in enumerate(valid):
        # Higher percentile means better performance
        percentile = 1.0 if count == 1 else 1.0 - (i / (count - 1))
        ranks[record["id"]] = percentile

    return ranks


def main():
    if not INPUT_FILE.exists():
        print(f"Missing file: {INPUT_FILE}")
        print("Run organize_alphas.py first.")
        return

    organized = load_json(INPUT_FILE)

    records = []

    for field_group, group_data in organized.get("field_groups", {}).items():
        for alpha in group_data.get("alphas", []):
            record = dict(alpha)
            record["field_group"] = field_group
            records.append(record)

    # Exclude unmatched alphas: field-family diversity cannot be assessed.
    records = [
        r for r in records
        if r.get("field_group")
        and r.get("expression")
        and isinstance(r.get("is_fitness"), (int, float))
        and isinstance(r.get("is_sharpe"), (int, float))
    ]

    if not records:
        print("No valid alpha records found.")
        return

    metrics = {
        "is_fitness": False,
        "is_sharpe": False,
        "train_fitness": False,
        "test_fitness": False,
        "train_sharpe": False,
        "test_sharpe": False,
        "is_turnover": True,
        "is_drawdown": True,
    }

    ranks = {}

    for metric, lower_is_better in metrics.items():
        ranks[metric] = percentile_ranks(
            records, metric, lower_is_better
        )

    # Score emphasizes performance, while considering robustness and costs.
    weights = {
        "is_fitness": 0.25,
        "is_sharpe": 0.20,
        "train_fitness": 0.15,
        "test_fitness": 0.15,
        "train_sharpe": 0.10,
        "test_sharpe": 0.05,
        "is_turnover": 0.05,
        "is_drawdown": 0.05,
    }

    for record in records:
        score = 0.0
        total_weight = 0.0

        for metric, weight in weights.items():
            rank = ranks[metric].get(record["id"])

            if rank is not None:
                score += rank * weight
                total_weight += weight

        record["selection_score"] = (
            score / total_weight if total_weight else 0
        )

        # Train/test Fitness gap: lower gap is more stable.
        train_fitness = record.get("train_fitness")
        test_fitness = record.get("test_fitness")

        if isinstance(train_fitness, (int, float)) and isinstance(
            test_fitness, (int, float)
        ):
            record["fitness_gap"] = abs(train_fitness - test_fitness)
        else:
            record["fitness_gap"] = None

    records.sort(
        key=lambda r: (
            r["selection_score"],
            r.get("is_fitness") or -999,
            r.get("is_sharpe") or -999,
        ),
        reverse=True,
    )

    selected = []
    selected_ids = set()
    selected_expressions = set()
    field_counts = {}

    # First pass: maximize field-family diversity.
    for record in records:
        field_group = record["field_group"]

        if field_counts.get(field_group, 0) >= 1:
            continue

        if record["expression"] in selected_expressions:
            continue

        selected.append(record)
        selected_ids.add(record["id"])
        selected_expressions.add(record["expression"])
        field_counts[field_group] = 1

        if len(selected) >= TARGET_COUNT:
            break

    # Second pass: fill remaining slots, allowing at most 2 per group.
    if len(selected) < TARGET_COUNT:
        for record in records:
            if record["id"] in selected_ids:
                continue

            field_group = record["field_group"]

            if field_counts.get(field_group, 0) >= MAX_PER_FIELD_GROUP:
                continue

            if record["expression"] in selected_expressions:
                continue

            selected.append(record)
            selected_ids.add(record["id"])
            selected_expressions.add(record["expression"])
            field_counts[field_group] = (
                field_counts.get(field_group, 0) + 1
            )

            if len(selected) >= TARGET_COUNT:
                break

    output = {
        "selection_method": "ranked performance with field-family diversity",
        "total_candidates": len(records),
        "selected_count": len(selected),
        "alphas": selected,
    }

    save_json(OUTPUT_JSON, output)

    if selected:
        columns = [
            "id",
            "field_group",
            "selection_score",
            "is_fitness",
            "is_sharpe",
            "train_fitness",
            "test_fitness",
            "train_sharpe",
            "test_sharpe",
            "is_turnover",
            "is_drawdown",
            "fitness_gap",
            "neutralization",
            "decay",
            "expression",
        ]

        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()

            for record in selected:
                writer.writerow({
                    column: record.get(column)
                    for column in columns
                })

    print("\nSelection complete.")
    print(f"Candidates evaluated: {len(records)}")
    print(f"Selected: {len(selected)}")
    print(f"JSON: {OUTPUT_JSON}")
    print(f"CSV:  {OUTPUT_CSV}")

    print("\nSelected alphas:")
    for i, record in enumerate(selected, 1):
        print(
            f"{i:2}. {record['id']} | "
            f"Fitness={record.get('is_fitness')} | "
            f"Sharpe={record.get('is_sharpe')} | "
            f"Field={record['field_group']}"
        )


if __name__ == "__main__":
    main()
