import json
import unittest
from copy import deepcopy
from pathlib import Path

from planner import plan


EXAMPLE = Path(__file__).resolve().parents[1] / "docs/examples/planner-contract.json"


class PlannerTest(unittest.TestCase):
    def setUp(self):
        self.example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.request = self.example["request"]

    def delayed_request(self, completed=False, now="10:20"):
        initial = plan(self.request)
        installer, repairer = initial["routes"]
        install_start, first_visit, *_ = installer["steps"]
        repair_start, repair_visit, *_ = repairer["steps"]
        first_visit.update(
            status="completed" if completed else "in_progress",
            end_at="2026-11-13T11:15:00+05:00",
        )
        self.request["as_of"] = f"2026-11-13T{now}:00+05:00"
        self.request["current_state"] = {
            "workers": [
                {
                    "worker_id": "W-I", "location_id": "A", "stock": {"router": 1},
                    "available_at": first_visit["end_at"],
                    "locked_steps": [{**install_start, "status": "completed"}, first_visit],
                },
                {
                    "worker_id": "W-R", "location_id": "E", "stock": {},
                    "available_at": repair_visit["end_at"],
                    "locked_steps": [
                        {**repair_start, "status": "completed"},
                        {**repair_visit, "status": "completed" if completed else "in_progress"},
                    ],
                },
            ],
            "previous_assignments": [
                {"worker_id": route["worker_id"], "order_id": step["order_id"],
                 "planned_arrival_at": step["arrival_at"]}
                for route in initial["routes"] for step in route["steps"] if step["type"] == "visit"
            ],
        }
        return self.request

    def test_initial_plan_matches_example(self):
        self.assertEqual(plan(self.request), self.example["response"])

    def test_delay_keeps_in_progress_visit_and_proposes_reschedule(self):
        request = self.delayed_request()
        original = deepcopy(request)
        result = plan(request)
        self.assertEqual(request, original)
        locked = request["current_state"]["workers"][0]["locked_steps"]
        self.assertEqual(result["routes"][0]["steps"][:2], locked)
        self.assertIn({"order_id": "I-02", "reason_code": "SLOT_UNREACHABLE"}, result["unassigned"])
        self.assertEqual(result["risks"], [{
            "order_id": "I-02", "worker_id": "W-I",
            "estimated_arrival_at": "2026-11-13T11:35:00+05:00",
            "reason_code": "SLOT_UNREACHABLE", "action": {"type": "propose_reschedule"},
        }])

    def test_completed_visit_keeps_actual_times_and_risk_requires_manual_review(self):
        request = self.delayed_request(completed=True, now="11:15")
        # Completed orders may already have been removed from the active list by the server.
        request["orders"] = [order for order in request["orders"] if order["id"] not in {"I-01", "R-01"}]
        result = plan(request)
        locked = request["current_state"]["workers"][0]["locked_steps"]
        self.assertEqual(result["routes"][0]["steps"][:2], locked)
        self.assertEqual(result["risks"][0]["estimated_arrival_at"], "2026-11-13T11:35:00+05:00")
        self.assertEqual(result["risks"][0]["action"], {"type": "manual_review"})

    def test_reassignment_requires_a_feasible_replacement(self):
        request = self.delayed_request()
        installer = request["workers"][0]
        request["workers"].append({**installer, "id": "W-X", "stock": {"router": 1}})
        request["current_state"]["workers"].append({
            "worker_id": "W-X", "location_id": "C", "stock": {"router": 1},
            "available_at": request["as_of"], "locked_steps": [],
        })
        result = plan(request)
        self.assertEqual(result["risks"][0]["action"], {"type": "reassign", "worker_id": "W-X"})
        replacement = result["routes"][2]
        visit = next(step for step in replacement["steps"] if step.get("order_id") == "I-02")
        self.assertEqual(visit["arrival_at"], "2026-11-13T11:00:00+05:00")


if __name__ == "__main__":
    unittest.main()
