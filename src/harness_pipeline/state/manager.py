"""Persistent state management for HARNESS PIPELINE research runs."""

import copy
import hashlib
import json
import os
import tempfile
import uuid

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateManager:
    """Create, save, resume, and track alpha research runs."""

    def __init__(
        self,
        state_path: str | Path = "data/pipeline_state.json",
    ):
        self.state_path = Path(state_path)

        self._state: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "active_run_id": None,
            "runs": {},
        }

        if self.state_path.exists():
            self._load()

    def _load(self) -> None:
        try:
            with self.state_path.open("r", encoding="utf-8") as file:
                state = json.load(file)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Pipeline state file contains invalid JSON: "
                f"{self.state_path}"
            ) from exc

        if not isinstance(state, dict):
            raise ValueError("Pipeline state must be a JSON object.")

        if state.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Unsupported pipeline state schema version.")

        if not isinstance(state.get("runs"), dict):
            raise ValueError("Pipeline runs must be a dictionary.")

        active_id = state.get("active_run_id")

        if active_id is not None and active_id not in state["runs"]:
            raise ValueError("Active run ID does not exist.")

        self._state = state

    def save(self) -> None:
        """Persist state using an atomic file replacement."""

        self.state_path.parent.mkdir(parents=True, exist_ok=True)

        temp_path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.state_path.parent,
                prefix=f".{self.state_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as file:
                temp_path = Path(file.name)

                json.dump(
                    self._state,
                    file,
                    indent=2,
                    ensure_ascii=False,
                )

                file.flush()
                os.fsync(file.fileno())

            os.replace(temp_path, self.state_path)

        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()

    @property
    def active_run_id(self) -> str | None:
        return self._state["active_run_id"]

    def _get_run(self, run_id: str | None = None) -> dict:
        run_id = run_id or self.active_run_id

        if run_id is None:
            raise RuntimeError("No active research run.")

        run = self._state["runs"].get(run_id)

        if run is None:
            raise KeyError(f"Research run not found: {run_id}")

        return run

    def start_run(
        self,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Create a new research run."""

        if self.active_run_id is not None:
            raise RuntimeError(
                "An active run already exists. Complete or resume it first."
            )

        run_id = uuid.uuid4().hex[:12]
        now = _timestamp()

        self._state["runs"][run_id] = {
            "run_id": run_id,
            "status": "running",
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "metadata": metadata or {},
            "checkpoint": {
                "stage": "initialized",
                "details": {},
                "updated_at": now,
            },
            "candidates": {},
            "failures": [],
        }

        self._state["active_run_id"] = run_id
        self.save()

        return run_id

    def resume_run(self, run_id: str | None = None) -> str:
        """Resume an existing research run."""

        if self.active_run_id is not None:
            raise RuntimeError(
                "Another research run is currently active."
            )

        run = self._get_run(run_id)

        if run["status"] == "completed":
            raise RuntimeError("Cannot resume a completed run.")

        run["status"] = "running"
        run["updated_at"] = _timestamp()

        self._state["active_run_id"] = run["run_id"]
        self.save()

        return run["run_id"]

    def checkpoint(
        self,
        stage: str,
        details: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> None:
        """Save progress at a particular pipeline stage."""

        if not stage.strip():
            raise ValueError("Checkpoint stage cannot be empty.")

        run = self._get_run(run_id)
        now = _timestamp()

        run["checkpoint"] = {
            "stage": stage,
            "details": details or {},
            "updated_at": now,
        }

        run["updated_at"] = now
        self.save()

    def add_candidate(
        self,
        expression: str,
        candidate_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> str:
        """Register an alpha candidate without duplicating expressions."""

        if not expression or not expression.strip():
            raise ValueError("Alpha expression cannot be empty.")

        run = self._get_run(run_id)

        candidate_id = candidate_id or hashlib.sha256(
            expression.strip().encode("utf-8")
        ).hexdigest()[:16]

        candidates = run["candidates"]

        if candidate_id in candidates:
            if candidates[candidate_id]["expression"] != expression:
                raise ValueError(
                    "Candidate ID already belongs to another expression."
                )

            return candidate_id

        candidates[candidate_id] = {
            "candidate_id": candidate_id,
            "expression": expression,
            "status": "discovered",
            "metadata": metadata or {},
            "simulation": None,
            "created_at": _timestamp(),
        }

        run["updated_at"] = _timestamp()
        self.save()

        return candidate_id

    def record_simulation(
        self,
        candidate_id: str,
        metrics: dict[str, Any],
        status: str = "completed",
        run_id: str | None = None,
    ) -> None:
        """Store simulation results for a candidate."""

        run = self._get_run(run_id)
        candidate = run["candidates"].get(candidate_id)

        if candidate is None:
            raise KeyError(f"Candidate not found: {candidate_id}")

        candidate["simulation"] = {
            "status": status,
            "metrics": metrics,
            "recorded_at": _timestamp(),
        }

        candidate["status"] = (
            "simulated" if status == "completed" else status
        )

        run["updated_at"] = _timestamp()
        self.save()

    def record_failure(
        self,
        stage: str,
        message: str,
        candidate_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        """Preserve errors and failure feedback."""

        run = self._get_run(run_id)

        run["failures"].append({
            "stage": stage,
            "message": message,
            "candidate_id": candidate_id,
            "recorded_at": _timestamp(),
        })

        run["updated_at"] = _timestamp()
        self.save()

    def fail_run(self, run_id: str | None = None) -> None:
        """Mark a run as failed and release it as the active run."""

        run = self._get_run(run_id)
        now = _timestamp()
        run["status"] = "failed"
        run["completed_at"] = now
        run["updated_at"] = now

        if self.active_run_id == run["run_id"]:
            self._state["active_run_id"] = None

        self.save()

    def complete_run(self, run_id: str | None = None) -> None:
        """Mark a research run as completed."""

        run = self._get_run(run_id)

        now = _timestamp()

        run["status"] = "completed"
        run["completed_at"] = now
        run["updated_at"] = now

        if self.active_run_id == run["run_id"]:
            self._state["active_run_id"] = None

        self.save()

    def get_run(self, run_id: str | None = None) -> dict:
        """Return a safe copy of a research run."""

        return copy.deepcopy(self._get_run(run_id))

    def list_runs(self) -> list[dict]:
        """Return summaries of all saved research runs."""

        return [
            {
                "run_id": run["run_id"],
                "status": run["status"],
                "created_at": run["created_at"],
                "updated_at": run["updated_at"],
                "candidate_count": len(run["candidates"]),
                "failure_count": len(run["failures"]),
                "checkpoint": run["checkpoint"]["stage"],
            }
            for run in self._state["runs"].values()
        ]
