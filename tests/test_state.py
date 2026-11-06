import json
import tempfile
import unittest

from pathlib import Path
from harness_pipeline.state import StateManager


class TestStateManager(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "state.json"
        self.manager = StateManager(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_create_run(self):
        run_id = self.manager.start_run({"universe": "USA"})
        run = self.manager.get_run(run_id)

        self.assertEqual(run["status"], "running")
        self.assertEqual(run["metadata"]["universe"], "USA")

    def test_checkpoint_persistence(self):
        run_id = self.manager.start_run()
        self.manager.checkpoint("simulation", {"completed": 15})

        restored = StateManager(self.path)
        run = restored.get_run(run_id)

        self.assertEqual(run["checkpoint"]["stage"], "simulation")
        self.assertEqual(run["checkpoint"]["details"]["completed"], 15)

    def test_resume_interrupted_run(self):
        run_id = self.manager.start_run()
        self.manager.checkpoint("generation")

        # Simulate a process interruption.
        self.manager._state["active_run_id"] = None
        self.manager.save()

        restored = StateManager(self.path)
        self.assertEqual(restored.resume_run(run_id), run_id)

    def test_add_candidate(self):
        self.manager.start_run()

        candidate_id = self.manager.add_candidate(
            "ts_rank(est_grossincome, 20)"
        )

        run = self.manager.get_run()

        self.assertIn(candidate_id, run["candidates"])
        self.assertEqual(
            run["candidates"][candidate_id]["status"], "discovered"
        )

    def test_duplicate_candidate(self):
        self.manager.start_run()

        expression = "ts_rank(est_grossincome, 20)"

        first = self.manager.add_candidate(expression)
        second = self.manager.add_candidate(expression)

        self.assertEqual(first, second)
        self.assertEqual(len(self.manager.get_run()["candidates"]), 1)

    def test_record_simulation(self):
        self.manager.start_run()

        candidate_id = self.manager.add_candidate(
            "ts_rank(est_grossincome, 20)"
        )

        metrics = {"sharpe": 1.45, "fitness": 1.12}

        self.manager.record_simulation(candidate_id, metrics)

        candidate = self.manager.get_run()["candidates"][candidate_id]

        self.assertEqual(candidate["status"], "simulated")
        self.assertEqual(
            candidate["simulation"]["metrics"]["sharpe"], 1.45
        )

    def test_record_failure(self):
        self.manager.start_run()
        self.manager.record_failure("simulation", "Simulation rejected")

        run = self.manager.get_run()

        self.assertEqual(len(run["failures"]), 1)
        self.assertEqual(run["failures"][0]["stage"], "simulation")

    def test_complete_run(self):
        run_id = self.manager.start_run()
        self.manager.complete_run()

        run = self.manager.get_run(run_id)

        self.assertEqual(run["status"], "completed")
        self.assertIsNone(self.manager.active_run_id)
        self.assertIsNotNone(run["completed_at"])

    def test_invalid_json(self):
        self.path.write_text("{invalid json", encoding="utf-8")

        with self.assertRaises(ValueError):
            StateManager(self.path)

    def test_invalid_checkpoint(self):
        self.manager.start_run()

        with self.assertRaises(ValueError):
            self.manager.checkpoint("")

    def test_valid_json_persistence(self):
        self.manager.start_run()

        with self.path.open(encoding="utf-8") as file:
            state = json.load(file)

        self.assertEqual(state["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
