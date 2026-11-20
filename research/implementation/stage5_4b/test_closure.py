"""C01, input-state and dated-capacity regressions."""

from copy import deepcopy
import unittest

from .__main__ import unique_keys
from .demo import construction_demo
from .engine import solve, validate
from .fixtures import normalize_reference, reference_cases


def case(key):
    return normalize_reference(reference_cases()[key])


class ClosureTests(unittest.TestCase):
    def test_c01_corrected_and_historical_fixtures(self):
        for holiday, expected in ((False, 40445), (True, 41885)):
            with self.subTest(holiday=holiday):
                old = solve(construction_demo(holiday, version="v1.0"))
                self.assertEqual(old["status"], "INFEASIBLE")
                self.assertIsNone(old["solver_status"])
                self.assertEqual(old["activities"], [])
                self.assertEqual(old["diagnostic"]["cause"], "RESERVATION_COVERAGE_PREDECESSOR")
                result = solve(construction_demo(holiday, version="v1.1"), time_limit=20)
                self.assertEqual(result["solver_status"], "OPTIMAL")
                self.assertEqual(result["objective_minutes"], expected)
                self.assertEqual(result["lower_bound_minutes"], expected)
                self.assertEqual(result["optimality_gap_minutes"], 0)
                self.assertTrue(result["validated"])
                self.assertEqual(result["resource_conflicts"], [])
                self.assertEqual(result["covered_activity_checks"], 108)
                self.assertEqual(len(result["activities"]), 70)
                self.assertEqual(len(result["reservations"]), 16)
                self.assertTrue(result["resource_occupancy"])
                self.assertTrue(result["supply_checks"])
                self.assertEqual(result["cost"]["total_direct_reference_eur"], 5103.32664)

    def test_input_states_and_conditional_provenance(self):
        for state, code in (("APPROVED", "INVALID_INPUT_STATE"), ("missing", "MISSING_INPUT"),
                            ("engineer_approved", "UNVERIFIED_APPROVAL")):
            for field in ("project_calendar", "activity", "resource", "release", "split", "event"):
                with self.subTest(state=state, field=field):
                    problem = case({"release": "RC05a", "split": "RC10a", "event": "RC12a"}.get(field, "RC01"))
                    row = {
                        "project_calendar": lambda: problem["project_calendar"],
                        "activity": lambda: problem["activities"][0],
                        "resource": lambda: next(iter(problem["resources"].values())),
                        "release": lambda: problem["reservations"][0]["release_condition"],
                        "split": lambda: problem["activities"][1]["split"],
                        "event": lambda: problem["inspection_pass_events"][0],
                    }[field]()
                    row["input_state"] = state
                    self.assertEqual(solve(problem)["diagnostic"]["code"], code)
        problem = case("RC12b")
        problem["inspection_pass_events"][0]["input_state"] = "missing"
        result = solve(problem)
        self.assertEqual(result["status"], "CONDITIONAL")
        self.assertEqual(result["inspection_pass_events"][0]["input_state"], "missing")
        self.assertEqual(result["activities"][0]["input_state"], "hypothetical_fixture")
        self.assertFalse(result["real_project_eligible"])
        for state in ("user_provided_project", "independently_measured"):
            problem = case("RC01")
            task = problem["activities"][0]
            task.update(input_state=state, evidence_ref="test evidence identifier")
            result = solve(problem)
            self.assertTrue(result["validated"])
            self.assertEqual(result["activities"][0]["input_state"], state)
            del task["evidence_ref"]
            self.assertEqual(solve(problem)["diagnostic"]["code"], "MISSING_INPUT")
        problem = case("RC01")
        del problem["activities"][0]["input_state"]
        self.assertEqual(solve(problem)["diagnostic"]["code"], "MISSING_INPUT")

    def test_crew_reduction_increase_and_zero_capacity(self):
        problem = case("RC01")
        crew = problem["resources"]["CREW_F"]
        crew.update(unit="worker", capacity=2, capacity_by_date={"2027-01-11": 1})
        reduced = solve(problem)
        self.assertEqual(reduced["objective_minutes"], 1610)
        self.assertEqual([row["duration_minutes"] for row in reduced["activities"]], [228, 196, 167])
        crew.update(capacity=1, capacity_by_date={"2027-01-11": 2})
        increased = solve(problem)
        self.assertEqual(increased["objective_minutes"], 370)
        crew["capacity_by_date"] = {"2027-01-11": 0}
        delayed = solve(problem)
        self.assertTrue(all(row["start"] >= "2027-01-12T08:00" for row in delayed["activities"]))
        problem["horizon_end"] = "2027-01-11T16:00"
        rejected = solve(problem)
        self.assertEqual(rejected["status"], "INFEASIBLE")
        self.assertFalse(rejected["activities"])

    def test_equipment_unavailability_and_closed_calendar(self):
        problem = case("RC02")
        problem["resources"]["CRANE"].update(unit="machine", capacity_by_date={"2027-01-11": 0})
        result = solve(problem)
        self.assertTrue(result["validated"])
        self.assertTrue(all(row["start"] >= "2027-01-12T08:00" for row in result["activities"]
                            if "CRANE" in row["resources"]))
        holiday = case("RC01")
        holiday["project_calendar"]["date_exceptions"] = ["2027-01-11"]
        holiday["resources"]["CREW_F"].update(unit="worker", capacity_by_date={"2027-01-11": 9})
        self.assertTrue(all(row["start"] >= "2027-01-12T08:00" for row in solve(holiday)["activities"]))

    def test_activity_crosses_capacity_boundary(self):
        problem = case("RC01")
        problem["project_start"] = "2027-01-11T23:00"
        calendar = problem["project_calendar"]
        calendar["working_windows"] = [{"weekday": 1, "start": "23:00", "end": "23:59"},
                                       {"weekday": 2, "start": "00:00", "end": "02:00"}]
        problem["tick_minutes"] = 1
        problem["horizon_end"] = "2027-01-12T02:00"
        task = problem["activities"][0]
        task["duration_minutes"] = 75
        problem["activities"] = [task]
        # The existing same-day calendar syntax leaves a 1-minute gap at midnight.
        # Two authorized segments straddle the local date change.
        task.update(interruption="split_allowed", split={
            "authorization_ref": "test", "max_segments": 2, "min_segment_minutes": 10,
            "retention_during_gap": "retain", "restart_overhead_minutes": 0,
            "same_mode_on_restart": True, "voluntary_pause": False, "input_state": "hypothetical_fixture",
        })
        pool = problem["resources"]["CREW_F"]
        pool.update(unit="worker", capacity_by_date={"2027-01-12": 1})
        valid = solve(problem)
        self.assertTrue(valid["validated"])
        self.assertGreaterEqual(valid["activities"][0]["finish"], "2027-01-12T00:00")
        pool["capacity_by_date"]["2027-01-12"] = 0
        with self.assertRaisesRegex(ValueError, "Overcapacity"):
            validate(problem, valid)
        self.assertEqual(solve(problem)["status"], "INFEASIBLE")

    def test_continuous_reservation_crosses_capacity_boundary(self):
        problem = case("RC05a")
        previous = solve(problem)
        self.assertTrue(previous["validated"])
        pool = problem["resources"]["FORMWORK_SET"]
        pool["capacity_by_date"] = {"2027-01-12": 0}
        with self.assertRaisesRegex(ValueError, "Overcapacity"):
            validate(problem, previous)
        result = solve(problem)
        self.assertTrue(result["validated"])
        self.assertTrue(all(not (row["start"] < "2027-01-13" and row["finish"] >= "2027-01-12T00:01")
                            for row in result["reservations"]))

    def test_successor_coverage_is_rejected_statically(self):
        problem = case("RC05a")
        problem["reservations"][0]["release_condition"]["all_of"][0]["activity_id"] = "E1-CURE"
        result = solve(problem)
        self.assertIsNone(result["solver_status"])
        self.assertEqual(result["diagnostic"]["cause"], "RESERVATION_COVERAGE_SUCCESSOR")

    def test_invalid_override_declarations(self):
        import json

        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            json.loads('{"2027-01-11": 1, "2027-01-11": 0}', object_pairs_hook=unique_keys)
        prototype = case("RC01")
        for changes in ({"2027-02-30": 1}, {"20270111": 1}, {"2027-01-11": -1},
                        {"2027-01-11": 1.2}, {"2027-01-11": True}, [{"2027-01-11": 1}]):
            with self.subTest(changes=changes):
                problem = deepcopy(prototype)
                problem["resources"]["CREW_F"].update(unit="worker", capacity_by_date=changes)
                self.assertEqual(solve(problem)["diagnostic"]["code"], "INVALID_CAPACITY_OVERRIDE")
        problem = case("RC01")
        problem["resources"]["CREW_F"].update(unit="m3/h", capacity_by_date={"2027-01-11": 2})
        self.assertEqual(solve(problem)["status"], "MODEL_INVALID")
        problem = case("RC01")
        problem["resources"]["UNUSED"] = {
            "resource_id": "UNUSED", "display_name": "Explicitly unused", "kind": "equipment",
            "unit": "machine", "calendar": "project", "capacity": 0, "explicit_none": True,
            "capacity_by_date": {"2027-01-11": 1}, "input_state": "hypothetical_fixture", "evidence_ref": "test",
        }
        self.assertEqual(solve(problem)["diagnostic"]["code"], "INVALID_CAPACITY_OVERRIDE")

