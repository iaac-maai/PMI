"""Integration result and conservative supply reporting regressions."""
import json
from pathlib import Path
import unittest
from tempfile import TemporaryDirectory

from pmi_core.application import run_controlled_pipeline

from pmi_core.schedule_result import schedule_result
from research.implementation.stage5_4b.engine import solve
from research.implementation.stage5_4b.fixtures import ROOT, normalize_reference, reference_cases
from research.implementation.stage5_4b.demo import construction_demo


F01 = ROOT / "research/validation/stage5_4b_independent/integration_prep/F01_split_pour_supply"


def split_case(variant, *, declared=True):
    problem = json.loads((F01 / "inputs" / f"f01_{variant}.json").read_text(encoding="utf-8"))
    if declared:
        problem["activities"][1].update(planned_placed_volume_m3=60, placement_profile="declared_constant_rate",
                                         evidence_ref="F01 scenarios: 60 m3 plan at 6 m3/h during placement")
    return problem


class IntegrationTests(unittest.TestCase):
    def test_f01_with_without_restart_and_daily_capacity(self):
        for variant, restart, total, makespan in (("A_restart_30", "3", "63", 4710),
                                                   ("B_restart_0", "0", "60", 4680)):
            problem = split_case(variant)
            result = solve(problem)
            self.assertEqual(result["objective_minutes"], makespan)
            self.assertEqual(result["supply_by_activity"][0]["planned_placed_volume_m3"], "60")
            self.assertEqual(result["supply_by_source"][0]["restart_capacity_allowance_m3"], restart)
            self.assertEqual(result["supply_totals"]["aggregate_total_capacity_allowance_m3"], total)
            days = {row["date"]: row for row in result["supply_checks"]}
            self.assertEqual(days["2027-01-15"]["planned_placed_volume_m3"], "24")
            self.assertEqual(days["2027-01-18"]["planned_placed_volume_m3"], "36")
            self.assertEqual(days["2027-01-18"]["total_capacity_allowance_m3"], "39" if restart == "3" else "36")
            self.assertEqual(result["cost"]["total_direct_reference_eur"], 7114.2)
        problem = split_case("A_restart_30")
        problem["resources"]["SUPPLY"]["max_volume_per_day_m3"] = 38
        self.assertNotEqual(solve(problem)["objective_minutes"], 4710)

    def test_unknown_physical_volume_is_not_inferred(self):
        result = solve(split_case("A_restart_30", declared=False))
        self.assertIsNone(result["supply_totals"]["aggregate_planned_placed_volume_m3"])
        self.assertEqual(result["supply_totals"]["aggregate_total_capacity_allowance_m3"], "63")

    def test_unsplit_rational_supply(self):
        problem = normalize_reference(reference_cases()["RC11b"])
        task = problem["activities"][0]
        problem["activities"] = [task]
        task.update(planned_placed_volume_m3="1/2")
        task["resources"]["SUPPLY"] = "1/3"
        result = solve(problem)
        self.assertTrue(result["validated"])
        report = result["supply_by_activity"][0]
        self.assertEqual(report["planned_placed_volume_m3"], "1/2")
        self.assertEqual(report["restart_capacity_allowance_m3"], "0")
        self.assertEqual(report["total_capacity_allowance_m3"], "1/2")

    def test_scope_and_all_contradictions(self):
        for cid, scope, duration in (("RC12c", "unblocked_subset", 150), ("RC13b", "conditional_projection", 5880)):
            optimized = solve(normalize_reference(reference_cases()[cid]))
            result = schedule_result(optimized=optimized)
            self.assertIsNone(result["proof"]["project_makespan_minutes"])
            self.assertEqual(result["proof"]["makespan_by_scope_minutes"], {scope: duration})
        for holiday in (False, True):
            result = solve(construction_demo(holiday))
            self.assertEqual(result["diagnostic"]["cause"], "RESERVATION_COVERAGE_PREDECESSOR")
            self.assertEqual(len(result["diagnostic"]["contradictions"]), 4)
            self.assertFalse(result["activities"])

    def test_completed_application_exports(self):
        for tick, expected in ((5, 14850), (15, 14880)):
            with TemporaryDirectory(prefix="pmi-r0-test-") as temp:
                result = run_controlled_pipeline(Path(__file__).with_name("r0_config.json"),
                    output=Path(temp) / "out", ifc_python=ROOT / ".venv/Scripts/python.exe",
                    planning_python=ROOT / ".venv-planning/Scripts/python.exe", tick=tick, root=ROOT)
            self.assertEqual(result["contract_version"], "pmi-schedule/1")
            self.assertEqual(result["proof"]["project_makespan_minutes"], expected)
            self.assertEqual(result["cost"]["total_direct_reference_eur"], 1172.5136)
            self.assertEqual(len(result["activities"]), 21)
            self.assertEqual(len({row["ifc_global_id"] for row in result["activities"]}), 3)
            self.assertEqual(len(result["pending_approvals"]), 88)
            self.assertFalse(result["real_project_eligible"])
