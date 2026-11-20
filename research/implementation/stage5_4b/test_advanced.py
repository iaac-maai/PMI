"""Advanced contract checks beyond the frozen reference oracles."""

from copy import deepcopy
import unittest

from .demo import construction_demo, cpm_comparison
from .engine import solve, validate
from .fixtures import normalize_reference, reference_cases


def case(key):
    return normalize_reference(reference_cases()[key])


class AdvancedTests(unittest.TestCase):
    def test_both_construction_fixtures_and_coverage_sensitivity(self):
        for holiday, expected in ((False, 40445), (True, 41885)):
            with self.subTest(holiday=holiday):
                problem = construction_demo(holiday)
                baseline = cpm_comparison(problem)
                self.assertEqual(baseline["makespan_minutes"], 16310)
                self.assertEqual(baseline["conflict_intervals"], 29)
                self.assertEqual(len(baseline["over_capacity_pools"]), 11)
                strict = solve(problem, time_limit=20)
                self.assertEqual(strict["solver_status"], "INFEASIBLE")
                self.assertFalse(strict["activities"])
                adjusted = solve(construction_demo(holiday, coverage_sensitivity=True), time_limit=20)
                self.assertEqual(adjusted["solver_status"], "OPTIMAL")
                self.assertTrue(adjusted["validated"])
                self.assertEqual(adjusted["objective_minutes"], expected)
                self.assertEqual(adjusted["lower_bound_minutes"], expected)
                self.assertEqual(len(adjusted["reservations"]), 16)
                self.assertEqual(adjusted["cost"]["total_direct_reference_eur"], 5103.32664)

    def test_supply_rate_and_daily_cap(self):
        problem = case("RC11b")
        supply = problem["resources"]["SUPPLY"]
        supply.update(capacity=5.0, max_volume_per_day_m3=4.25)
        for task in problem["activities"]:
            task["resources"]["SUPPLY"] = 2.5
        result = solve(problem)
        self.assertEqual(result["status"], "OPTIMAL")
        self.assertEqual(result["objective_minutes"], 1485)
        self.assertEqual(result["activities"][0]["resources"]["SUPPLY"], 2.5)
        loose = deepcopy(problem)
        del loose["resources"]["SUPPLY"]["max_volume_per_day_m3"]
        with self.assertRaisesRegex(ValueError, "Daily concrete supply limit"):
            validate(problem, solve(loose))

    def test_return_lead_and_unreachable_release(self):
        problem = case("RC05a")
        first, second = problem["reservations"]
        for row in (first, second):
            row["release_condition"]["return_lead_minutes"] = 1440
        result = solve(problem)
        self.assertTrue(result["validated"])
        a, b = sorted(result["reservations"], key=lambda row: row["start"])
        self.assertGreaterEqual(b["start"], a["finish"])
        invalid = deepcopy(result)
        invalid["reservations"][0]["finish"] = invalid["reservations"][0]["start"]
        with self.assertRaisesRegex(ValueError, "Reservation output mismatch"):
            validate(problem, invalid)
        first["release_condition"]["all_of"].append({"kind": "activity_finish", "activity_id": "E2-STRIP"})
        result = solve(problem)
        self.assertEqual(result["diagnostic"]["code"], "RESERVATION_UNRELEASED")

    def test_split_restart_and_retention(self):
        problem = case("RC10a")
        task = problem["activities"][1]
        task["split"].update(restart_overhead_minutes=15, retention_during_gap="retain")
        result = solve(problem)
        self.assertTrue(result["validated"])
        segments = result["activities"][1]["segments"]
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[-1][-1], "2027-01-18T14:15+01:00")
        task.update(is_pour=True)
        self.assertEqual(solve(problem)["diagnostic"]["code"], "SPLIT_NOT_AUTHORIZED")

    def test_named_recorded_release_and_return_lead(self):
        problem = case("RC12d")
        problem["resources"]["PANELS"] = {
            "resource_id": "PANELS", "display_name": "Panels", "kind": "reusable_asset",
            "unit": "piece", "capacity": 1, "calendar": "continuous",
        }
        problem["reservations"] = [{
            "reservation_id": "SET", "resource_id": "PANELS", "quantity": 1,
            "occupancy_basis": "continuous_elapsed",
            "start_event": {"kind": "activity_start", "activity_id": "R"},
            "release_condition": {
                "all_of": [{"kind": "activity_finish", "activity_id": "I"},
                           {"kind": "inspection_pass", "event_id": "EV-I"}],
                "return_lead_minutes": 30, "reshoring": "not_permitted",
            },
            "covers_activities": ["R", "I"],
        }]
        result = solve(problem)
        self.assertTrue(result["validated"])
        self.assertEqual(result["reservations"][0]["finish"], "2027-01-11T12:10+01:00")

