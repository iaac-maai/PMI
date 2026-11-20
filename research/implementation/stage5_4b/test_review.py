"""Regression checks for the Stage 5.4B targeted correctness review."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ortools.sat.python import cp_model

from .demo import construction_demo
from .engine import solve
from .fixtures import ROOT, frozen_r0, normalize_reference, reference_cases


def case(key):
    return normalize_reference(reference_cases()[key])


class ReviewTests(unittest.TestCase):
    def assert_rejected(self, problem, code):
        result = solve(problem)
        self.assertEqual(result["status"], "MODEL_INVALID")
        self.assertEqual(result["diagnostic"]["code"], code)
        self.assertIsNone(result["solver_status"])
        self.assertFalse(result["activities"])
        self.assertFalse(result["real_project_eligible"])
        return result

    def test_explicit_none_is_a_missing_input_when_demanded(self):
        problem = case("RC08b")
        problem["resources"]["FERRALLISTA"]["explicit_none"] = True
        self.assert_rejected(problem, "MISSING_INPUT")
        problem["resources"]["FERRALLISTA"]["capacity"] = 1
        self.assert_rejected(problem, "MISSING_INPUT")

    def test_mode_fields_require_a_selected_mode(self):
        for field, value in {
            "positive_capacity": {}, "demand_hours": {}, "reserved_without_bcca_demand": {},
            "reservation_reason": "hypothetical", "reservation_approval_ref": "AP-X-CREW-01",
        }.items():
            with self.subTest(field=field):
                problem = case("RC01")
                problem["activities"][0][field] = value
                self.assert_rejected(problem, "MODE_MISMATCH")

    def test_approval_and_fixture_metadata_are_verified(self):
        problem = case("RC01")
        problem["pending_approvals"][0]["status"] = "APPROVED"
        self.assertNotIn("pending_approvals", self.assert_rejected(problem, "UNVERIFIED_APPROVAL"))
        problem = case("RC01")
        del problem["pending_approvals"]
        result = solve(problem)
        self.assertEqual(len(result["pending_approvals"]), 88)
        self.assertTrue(all(row["status"] == "PENDING" for row in result["pending_approvals"]))
        problem["activities"][0]["pending_approval_ids"] = ["FAKE"]
        self.assert_rejected(problem, "UNVERIFIED_APPROVAL")
        problem = case("RC01")
        problem["fixture_exceptions"] = [{"id": "FAKE", "treatment": "skip capacity"}]
        self.assert_rejected(problem, "UNVERIFIED_FIXTURE_EXCEPTION")
        problem["fixture_exceptions"] = case("R0-5")["fixture_exceptions"]
        self.assert_rejected(problem, "UNVERIFIED_FIXTURE_EXCEPTION")
        problem = case("R0-5")
        problem["fixture_exceptions"][0]["treatment"] = "rerouted"
        self.assert_rejected(problem, "UNVERIFIED_FIXTURE_EXCEPTION")

    def test_infeasibility_reports_evidence_and_unknown_cause(self):
        problem = case("RC01")
        problem["horizon_end"] = "2027-01-11T16:00"
        result = solve(problem)
        self.assertEqual(result["solver_status"], "INFEASIBLE")
        self.assertEqual(result["diagnostic"]["code"], "HORIZON_EXHAUSTED")
        self.assertGreater(result["diagnostic"]["witness_completion"], "2027-01-11T16:00+01:00")
        self.assertFalse(result["activities"])
        structural = solve(construction_demo())
        self.assertEqual(structural["diagnostic"]["code"], "STRUCTURAL_INFEASIBILITY")
        self.assertEqual(structural["diagnostic"]["cause"], "RESERVATION_COVERAGE_PREDECESSOR")
        problem = case("RC11b")
        problem["resources"]["SUPPLY"]["max_volume_per_day_m3"] = 0
        unresolved = solve(problem)
        self.assertEqual(unresolved["solver_status"], "INFEASIBLE")
        self.assertEqual(unresolved["diagnostic"]["cause"], "UNDETERMINED")

    def test_calendar_exception_audit(self):
        for authorization, reason in ((None, "MISSING_AUTHORIZATION"), ("fabricated", "UNREGISTERED_AUTHORIZATION")):
            with self.subTest(reason=reason):
                problem = case("RC06")
                problem["calendar_exceptions"][0]["authorization_ref"] = authorization
                result = solve(problem)
                self.assertEqual(result["ignored_calendar_exceptions"],
                                 [{"exception_id": "CAL-EXC-RC06", "reason": reason}])
                n = next(row for row in result["activities"] if row["id"] == "N")
                self.assertEqual(n["start"], "2027-01-12T08:00+01:00")
        self.assertEqual(solve(case("RC06"))["ignored_calendar_exceptions"], [])

    def test_frozen_equipment_declarations_survive_and_are_required(self):
        equipment = {"CRANE", "CONCRETE_PUMP", "CONCRETE_DELIVERY"}
        for tick in (5, 15):
            with self.subTest(tick=tick):
                problem = frozen_r0(tick)
                result = solve(problem)
                self.assertTrue(all(result["resources"][key]["explicit_none"] for key in equipment))
                pours = [row for row in result["activities"] if row["reference_id"].endswith("-POUR")]
                self.assertEqual(len(pours), 3)
                self.assertTrue(all(set(row["explicit_none_equipment"]) == equipment for row in pours))
                self.assertTrue(all(not (row["resources"].keys() & equipment) for row in pours))
                del problem["resources"]["CONCRETE_DELIVERY"]
                self.assert_rejected(problem, "EXPLICIT_NONE_REQUIRED")

    def test_metrics_and_secondary_timestamp_provenance(self):
        problem = case("RC01")
        regular = solve(problem)
        self.assertEqual(regular["timestamp_source"], "secondary")
        self.assertIn(regular["secondary_solver_status"], {"OPTIMAL", "FEASIBLE"})
        original_solve = cp_model.CpSolver.solve
        calls = 0

        def starve_secondary(solver, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                solver.parameters.max_time_in_seconds = 1e-9
            return original_solve(solver, *args, **kwargs)

        with patch.object(cp_model.CpSolver, "solve", starve_secondary):
            primary = solve(problem)
        self.assertEqual(primary["timestamp_source"], "primary")
        self.assertEqual(primary["secondary_solver_status"], "UNKNOWN")
        for metric in ("objective_minutes", "lower_bound_minutes", "optimality_gap_minutes"):
            self.assertIs(type(primary[metric]), int)
            self.assertEqual(primary[metric], regular[metric])
        self.assertIs(type(primary["optimality_gap"]), float)
        self.assertEqual(primary["status"], "OPTIMAL")
        self.assertAlmostEqual(primary["runtime_seconds"],
                               primary["primary_runtime_seconds"] + primary["secondary_runtime_seconds"])
        infeasible = solve(case("RC07a"))
        self.assertIsNone(infeasible["timestamp_source"])

    def test_unsupported_input_injections(self):
        base = case("RC01")
        mutations = [
            lambda p: p.update(pressure_limit=2),
            lambda p: p["activities"][0].update(preemptible=True),
            lambda p: p["project_calendar"].update(plant_shutdowns=[]),
            lambda p: p.update(supply_sources=[{"resource_id": "FICTITIOUS"}]),
            lambda p: p.update(objective="minimize_cost"),
        ]
        for inject in mutations:
            problem = deepcopy(base)
            inject(problem)
            self.assert_rejected(problem, "UNSUPPORTED_CONSTRAINT")
        blocked = case("RC12c")
        blocked["activities"][-1]["preemptible"] = True
        self.assert_rejected(blocked, "UNSUPPORTED_CONSTRAINT")
        relation = case("RC02")
        relation["dependencies"][0]["relation"] = "SS"
        self.assert_rejected(relation, "UNSUPPORTED_RELATION")
        reservation = case("RC05a")
        reservation["reservations"][0]["release_condition"]["reshoring"] = "approved_with_ref"
        self.assert_rejected(reservation, "UNSUPPORTED_CONSTRAINT")
        with TemporaryDirectory() as temp:
            path = Path(temp) / "input.json"
            path.write_text(json.dumps(reservation), encoding="utf-8")
            result = subprocess.run([sys.executable, "-B", "-m", "research.implementation.stage5_4b",
                                     "--input", str(path)], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["diagnostic"]["code"], "UNSUPPORTED_CONSTRAINT")

