"""Run the research stages and persist progress in pipeline state."""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from auth import WQSession
from harness_pipeline.fields import FieldCatalog
from harness_pipeline.fields.fields import fetch_fields
from harness_pipeline.state import StateManager

DATA = ROOT / "data"
STATE_PATH = DATA / "pipeline_state.json"


def _load_ids(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Missing Alpha ID input file: {path}")
    return list(dict.fromkeys(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ))


def _run_stage(manager: StateManager, run_id: str, stage: str, script: str) -> None:
    manager.checkpoint(stage, {"status": "running"}, run_id=run_id)
    result = subprocess.run(
        [sys.executable, str(ROOT / script)],
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Stage {stage} failed with exit code {result.returncode}.")
    manager.checkpoint(stage, {"status": "completed"}, run_id=run_id)


def _record_fetch_failures(manager: StateManager, run_id: str) -> None:
    path = DATA / "fetched_alphas.json"
    if not path.exists():
        raise FileNotFoundError(f"Fetcher did not create {path}")
    records = json.loads(path.read_text(encoding="utf-8"))
    for alpha_id, record in records.items():
        if isinstance(record, dict) and record.get("_fetch_error"):
            manager.record_failure(
                "fetch",
                str(record["_fetch_error"]),
                candidate_id=alpha_id,
                run_id=run_id,
            )


def _record_selected(manager: StateManager, run_id: str) -> int:
    path = DATA / "top25_alphas.json"
    if not path.exists():
        raise FileNotFoundError(f"Selector did not create {path}")
    result = json.loads(path.read_text(encoding="utf-8"))
    selected = result.get("alphas", [])
    count = 0

    for record in selected:
        alpha_id = str(record.get("id") or "").strip()
        expression = str(record.get("expression") or "").strip()
        if not alpha_id or not expression:
            manager.record_failure(
                "selection",
                "Selected record is missing an alpha ID or expression.",
                candidate_id=alpha_id or None,
                run_id=run_id,
            )
            continue
        manager.add_candidate(
            expression,
            candidate_id=alpha_id,
            metadata={
                key: record.get(key)
                for key in (
                    "field_group", "fields", "selection_score", "is_fitness",
                    "is_sharpe", "train_fitness", "test_fitness",
                    "train_sharpe", "test_sharpe", "is_turnover", "is_drawdown",
                )
            },
            run_id=run_id,
        )
        count += 1
    return count



def _submit_selected_alphas(auto_submit: bool = False) -> int:
    retriever = ROOT / "top25_id_retriever.py"
    result = subprocess.run([sys.executable, str(retriever)], cwd=ROOT, check=False)
    if result.returncode != 0:
        print("Could not create the selected Alpha ID list; queue was not started.", file=sys.stderr)
        return result.returncode

    ids_path = DATA / "top25_alpha_ids.json"
    print(f"Starting submission queue from {ids_path.relative_to(ROOT)}.")
    queue_command = [sys.executable, str(ROOT / "submit_queue.py"), "--file", str(ids_path)]
    if auto_submit:
        queue_command.append("--yes-all")
    queue_result = subprocess.run(queue_command, cwd=ROOT, check=False)

    processors = (
        "create_submission_output.py",
        "filter_alphas.py",
        "get_failed_submissions_ids.py",
    )
    for script in processors:
        result = subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT, check=False)
        if result.returncode != 0:
            print(f"Submission output processing failed in {script}.", file=sys.stderr)
            return result.returncode
    return queue_result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--auto-submit",
        action="store_true",
        help="Skip per-alpha prompts for eligible, non-failing submissions.",
    )
    mode.add_argument(
        "--no-submit",
        action="store_true",
        help="Run research and selection stages without starting the queue.",
    )
    args = parser.parse_args()

    ids_path = DATA / "alpha_ids.txt"
    alpha_ids = _load_ids(ids_path)
    if not alpha_ids:
        print(f"No Alpha IDs found in {ids_path}.")
        return 1

    manager = StateManager(STATE_PATH)
    run_id = manager.start_run({
        "input_file": str(ids_path.relative_to(ROOT)),
        "input_count": len(alpha_ids),
        "field_settings": {"region": "USA", "universe": "TOP3000", "delay": 1},
        "selection_target": 25,
    })
    stage = "field_cache"

    try:
        manager.checkpoint(stage, {"status": "loading_or_fetching"}, run_id=run_id)
        session_manager = WQSession(credentials_file=str(ROOT / "credentials.json"))
        session_manager.login()
        fields = fetch_fields(
            session_manager.session,
            region="USA",
            universe="TOP3000",
            delay=1,
        )
        catalog = FieldCatalog.load()
        manager.checkpoint(
            "field_catalog_loaded",
            {"field_count": catalog.total_fields, "fetched_or_cached_count": len(fields)},
            run_id=run_id,
        )

        stage = "fetch"
        _run_stage(manager, run_id, stage, "fetch_alphas.py")
        _record_fetch_failures(manager, run_id)

        stage = "organize"
        _run_stage(manager, run_id, stage, "organize_alphas.py")
        if not (DATA / "alphas_by_field.json").exists():
            raise FileNotFoundError("Organizer did not create data/alphas_by_field.json")

        stage = "select"
        _run_stage(manager, run_id, stage, "select_alphas.py")
        selected_count = _record_selected(manager, run_id)
        manager.checkpoint(
            "selection_complete",
            {"selected_count": selected_count, "target_count": 25},
            run_id=run_id,
        )
        manager.complete_run(run_id)
        print(f"Pipeline run {run_id} completed; selected candidates: {selected_count}.")

        if args.no_submit:
            print("Submission queue skipped by --no-submit; selected and watchlist files are ready.")
            return 0

        print("Starting the selected-alpha submission queue.")
        if args.auto_submit:
            print("Auto-submit enabled for eligible alphas; failed self-correlation checks will be skipped.")
        else:
            print("The queue will ask for confirmation for each alpha.")
        return _submit_selected_alphas(auto_submit=args.auto_submit)

    except Exception as exc:
        manager.record_failure(stage, str(exc), run_id=run_id)
        manager.fail_run(run_id)
        print(f"Pipeline run {run_id} failed during {stage}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

