"""Checks for controlled IFC4D export and the presentation contract."""
import copy
from datetime import datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import ifcopenshell
import ifcopenshell.geom

from pmi_core.adapters.ifc4d import _export_live, export_controlled_ifc4d

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "research/implementation/stage5_2/controlled_frame.ifc"
ACCEPTED = ROOT / "research/implementation/stage5_4b_integration"


class ControlledIfc4dTest(unittest.TestCase):
    def test_both_resolutions_preserve_geometry_ids_and_dates(self):
        original = ifcopenshell.open(str(SOURCE))
        settings = ifcopenshell.geom.settings()
        settings.set("use-world-coords", True)

        def meshes(model):
            result = {}
            for element in model.by_type("IfcElement"):
                shape = ifcopenshell.geom.create_shape(settings, element)
                result[element.GlobalId] = (shape.geometry.verts, shape.geometry.faces)
            return result

        expected_meshes = meshes(original)
        prior_guids = None
        with tempfile.TemporaryDirectory() as tmp:
            for tick in (5, 15):
                with self.subTest(tick=tick):
                    accepted = ACCEPTED / f"r0_{tick}_schedule.json"
                    schedule = json.loads(accepted.read_bytes())
                    target = Path(tmp) / str(tick)
                    export_controlled_ifc4d(SOURCE, accepted, target)
                    model = ifcopenshell.open(str(target / "scheduled.ifc"))
                    tasks = {task.Identification: task for task in model.by_type("IfcTask")}
                    guids = {key: task.GlobalId for key, task in tasks.items()}
                    self.assertEqual(meshes(model), expected_meshes)
                    self.assertEqual(len(tasks), 24)
                    if prior_guids is not None:
                        self.assertEqual(guids, prior_guids)
                    prior_guids = guids
                    viewer = json.loads((target / "viewer.json").read_bytes())
                    self.assertEqual(viewer["status"]["PendingApprovalCount"], 88)
                    self.assertFalse(viewer["status"]["RealProjectEligible"])
                    self.assertEqual(viewer["status"]["ApprovalStatus"], "PENDING")
                    self.assertEqual(len(model.by_type("IfcRelSequence")), 28)
                    for row in schedule["activities"]:
                        key = row["activity_id"]
                        gid = row["ifc_global_id"]
                        timing = tasks[key].TaskTime
                        self.assertEqual(timing.ScheduleStart, datetime.fromisoformat(row["optimized"]["start"]).isoformat())
                        self.assertEqual(timing.ScheduleFinish, datetime.fromisoformat(row["optimized"]["finish"]).isoformat())
                        self.assertEqual(viewer["activities_by_id"][key]["cpm"], row["baseline"])
                        self.assertEqual(viewer["activities_by_id"][key]["cp_sat"], row["optimized"])
                        self.assertIn(key, viewer["activity_ids_by_element_global_id"][gid])

    def test_rejects_unmapped_benchmark_and_invalid_r0(self):
        accepted = json.loads((ACCEPTED / "r0_5_schedule.json").read_bytes())
        approved = copy.deepcopy(accepted)
        approved["pending_approvals"][0]["status"] = "APPROVED"
        incomplete = copy.deepcopy(accepted)
        incomplete["dependencies"].pop()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            target = folder / "bundle"
            with self.assertRaisesRegex(ValueError, "registered IFC-backed R0"):
                export_controlled_ifc4d(SOURCE, ACCEPTED / "original_v1.1_schedule.json", target)
            for data, message in ((approved, "pending approvals"), (incomplete, "R0 dependencies")):
                changed = folder / "schedule.json"
                changed.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    export_controlled_ifc4d(SOURCE, changed, target)
            self.assertFalse(target.exists())

    def test_rejects_arbitrary_ifc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            changed = root / "other.ifc"
            changed.write_bytes(SOURCE.read_bytes() + b"\n")
            target = root / "bundle"
            with self.assertRaisesRegex(ValueError, "registered IFC-backed R0"):
                export_controlled_ifc4d(changed, ACCEPTED / "r0_5_schedule.json", target)
            self.assertFalse(target.exists())

    def test_forged_final_activity_is_rejected_by_standalone_cli(self):
        schedule = json.loads((ACCEPTED / "r0_5_schedule.json").read_bytes())
        last = max(schedule["activities"], key=lambda item: item["optimized"]["finish"])["optimized"]
        start, finish = [(datetime.fromisoformat(last[field]) + timedelta(days=1)).isoformat(timespec="minutes")
                         for field in ("start", "finish")]
        last.update(start=start, finish=finish, segments=[[start, finish]])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            altered = root / "schedule.json"
            target = root / "bundle"

            def reject(message):
                altered.write_text(json.dumps(schedule), encoding="utf-8")
                result = subprocess.run([sys.executable, "-B", "-m", "pmi_core.adapters.ifc4d",
                                         "--source", str(SOURCE), "--schedule", str(altered),
                                         "--output", str(target)], cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(message, result.stderr)
                self.assertEqual(list(root.iterdir()), [altered])

            reject("Optimized makespan differs")
            proof = schedule["proof"]
            proof["project_makespan_minutes"] += 1440
            reject("Optimal R0 proof does not match")
            proof["lower_bound_minutes"] += 1440
            proof["makespan_by_scope_minutes"]["complete_project"] += 1440
            reject("SHA-256 does not match a registered accepted R0 artifact")

            # A caller-supplied matching digest also cannot defeat live verification.
            digest = sha256(altered.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "content or provenance differs"):
                _export_live(SOURCE, altered, target, digest)
            self.assertFalse(target.exists())

    def test_rejects_duration_edits_and_missing_provenance(self):
        schedule = json.loads((ACCEPTED / "r0_5_schedule.json").read_bytes())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            altered = root / "schedule.json"
            target = root / "bundle"
            activity = schedule["activities"][0]["optimized"]
            for field in ("working_minutes", "elapsed_minutes"):
                activity[field] += 1
                altered.write_text(json.dumps(schedule), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, f"Optimized {field} differs"):
                    export_controlled_ifc4d(SOURCE, altered, target)
                activity[field] -= 1
            schedule.pop("evidence")
            altered.write_text(json.dumps(schedule), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256 does not match"):
                export_controlled_ifc4d(SOURCE, altered, target)
            digest = sha256(altered.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "provenance is incomplete"):
                _export_live(SOURCE, altered, target, digest)
            with self.assertRaisesRegex(ValueError, "SHA-256 differs from the application run"):
                _export_live(SOURCE, altered, target, "0" * 64)
            self.assertFalse(target.exists())

    def test_does_not_replace_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            sentinel = path / "scheduled.ifc"
            sentinel.write_bytes(b"existing")
            with self.assertRaisesRegex(ValueError, "already exists"):
                export_controlled_ifc4d(SOURCE, ACCEPTED / "r0_5_schedule.json", path)
            self.assertEqual(sentinel.read_bytes(), b"existing")
