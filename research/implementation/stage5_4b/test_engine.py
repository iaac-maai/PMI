"""Reference outcomes, frozen handover and timestamp validation regressions."""

from copy import deepcopy
from hashlib import sha256
import unittest

import ortools

from .engine import solve, validate
from .fixtures import REFERENCES, approvals, csv_rows, frozen_r0, normalize_reference, read_json, reference_cases


DEFERRED_CASES = {
    "RC05a", "RC05b", "RC10a", "RC10c", "RC11a", "RC11b",
    "RC12a", "RC12b", "RC12c", "RC12d", "RC12e", "RC13a", "RC13b",
}


class SchedulingTests(unittest.TestCase):
    def test_reference_cases(self):
        expected_csv = {row["case_id"]: row for row in csv_rows(REFERENCES / "cpsat_expected_results.csv")}
        for key, case in reference_cases().items():
            if key == "DEMO-H1":
                continue
            with self.subTest(case=key):
                result = solve(normalize_reference(case))
                if key in DEFERRED_CASES:
                    self.assertEqual(result["status"], "MODEL_INVALID")
                    self.assertEqual(result["diagnostic"]["code"], "UNSUPPORTED_CONSTRAINT")
                    self.assertIsNone(result["solver_status"])
                    self.assertEqual(result["activities"], [])
                    continue
                expected = case["expected"]
                self.assertEqual(result["status"], expected["expected_status"])
                if key in expected_csv:
                    self.assertEqual(result["status"], expected_csv[key]["expected_status"])
                if result["status"] != "OPTIMAL":
                    self.assertEqual(result["diagnostic"]["code"], expected_csv[key]["preflight_code"])
                    self.assertFalse(result["activities"])
                    continue
                self.assertEqual(result["solver_status"], "OPTIMAL")
                self.assertTrue(result["validated"])
                self.assertEqual(result["objective_minutes"], expected["optimal_makespan_minutes"])
                self.assertEqual(result["lower_bound_minutes"], result["objective_minutes"])
                self.assertEqual(result["optimality_gap"], 0)
                self.assertEqual(result["completion_local"], expected["completion_local"])
                if expected.get("unique_optimal_schedule") or key == "RC06-D":
                    actual = {row["id"]: row for row in result["activities"]}
                    for row in expected.get("reference_schedule", expected.get("schedule")):
                        for field in ("start", "finish", "segments"):
                            if field in row:
                                self.assertEqual(actual[row["id"]][field], row[field], (row["id"], field))

    def test_frozen_r0(self):
        self.assertEqual(ortools.__version__, "9.15.6755")
        for tick, target in ((5, 14850), (15, 14880)):
            with self.subTest(tick=tick):
                problem = frozen_r0(tick)
                result = solve(problem)
                self.assertEqual(result["status"], "OPTIMAL", result.get("diagnostic"))
                self.assertEqual(result["cpm_baseline_minutes"], target)
                self.assertEqual(result["objective_minutes"], target)
                self.assertEqual(result["cost"]["total_direct_reference_eur"], 1172.5136)
                self.assertEqual(len(problem["dependencies"]), 28)
                self.assertEqual(len(result["activities"]), 21)
                self.assertEqual(len(result["pending_approvals"]), 88)
                self.assertFalse(result["real_project_eligible"])
                pour = next(row for row in result["activities"] if row["reference_id"] == "C-POUR")
                self.assertNotEqual(pour["id"], pour["reference_id"])
                self.assertEqual(pour["crew_mode"], "HYP-CONC")
                self.assertEqual(pour["resources"]["OFICIAL_1"], 1)
                self.assertEqual(pour["reserved_without_bcca_demand"], {"OFICIAL_1": 1})
                pour_input = next(row for row in problem["activities"] if row["id"] == pour["id"])
                del pour_input["resources"]["OFICIAL_1"]
                self.assertEqual(solve(problem)["diagnostic"]["code"], "MODE_MISMATCH")

    def test_unauthorized_calendar_exception_uses_default(self):
        problem = normalize_reference(reference_cases()["RC06"])
        del problem["calendar_exceptions"][0]["authorization_ref"]
        result = solve(problem)
        rows = {row["id"]: row for row in result["activities"]}
        self.assertEqual(rows["N"]["start"], "2027-01-12T08:00+01:00")

    def test_calendar_validation(self):
        problem = normalize_reference(reference_cases()["RC04"])
        problem["project_calendar"]["working_windows"][0]["start"] = "08:01"
        result = solve(problem)
        self.assertEqual(result["diagnostic"]["code"], "TICK_MISALIGNED")
        self.assertIsNone(result["solver_status"])

    def test_validation_rejects_conflicting_timestamps(self):
        problem = normalize_reference(reference_cases()["RC01"])
        result = solve(problem)
        broken = deepcopy(result)
        activities = {row["id"]: row for row in broken["activities"]}
        start, finish = "2027-01-11T08:00+01:00", "2027-01-11T11:20+01:00"
        activities["B"].update(start=start, finish=finish, segments=[[start, finish]])
        other = next(row for row in broken["activities"] if row["id"] != "B"
                     and row["start"].startswith("2027-01-11"))
        if other["start"] >= finish:
            start, finish = "2027-01-11T12:40+01:00", "2027-01-11T16:00+01:00"
            activities["B"].update(start=start, finish=finish, segments=[[start, finish]])
        with self.assertRaisesRegex(ValueError, "Overcapacity"):
            validate(problem, broken)

    def test_pending_approvals_and_reference_hashes(self):
        self.assertEqual(len(approvals()), 88)
        manifest = read_json(REFERENCES / "deliverable_manifest.json")
        self.assertGreater(len(manifest["files"]), 8)
        for entry in manifest["files"]:
            with self.subTest(path=entry["path"]):
                self.assertEqual(sha256((REFERENCES / entry["path"]).read_bytes()).hexdigest(),
                                 entry["sha256"])


if __name__ == "__main__":
    unittest.main()

