"""Integration checks for the new fixture and the local linked viewer."""
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from threading import Thread
from types import SimpleNamespace
import unittest

from .application import MODULE, ROOT, SOURCE_SHA
from .fallback import build_server, workspace
from .speckle_identity import identity_map


class ControlledMilestoneTest(unittest.TestCase):
    def test_identity_mapping_uses_ifc_properties_not_the_speckle_id(self):
        rows = [SimpleNamespace(properties={"IFC GUID": "sample"}, application_id="different")]
        self.assertEqual(identity_map(rows, {"sample"}), {
            "sample": {"speckle_application_id": "different", "viewer_object_id": None},
        })
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            identity_map(rows + rows, {"sample"})
        with self.assertRaisesRegex(ValueError, "Missing"):
            identity_map(rows, {"unobserved"})
        rows[0].properties["IFC Attributes.GlobalId"] = "conflicting"
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            identity_map(rows, {"sample"})

    def test_model_to_viewer(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("first", "second"):
                destination = root / name
                run = subprocess.run([
                    str(ROOT / ".venv-planning/Scripts/python.exe"), "-B", "-m", f"{MODULE}.application",
                    "--output", str(destination),
                ], cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stderr)
            def read(run, name):
                return json.loads((root / run / name).read_bytes())
            schedule = read("first", "schedule.json")
            second = read("second", "schedule.json")
            for key in ("activities", "dependencies", "work_packages", "element_quantities", "cpm"):
                self.assertEqual(schedule[key], second[key])
            self.assertEqual(schedule["source_ifc_sha256"], SOURCE_SHA)
            self.assertEqual(len(schedule["pending_approvals"]), 88)
            self.assertFalse(schedule["real_project_eligible"])
            self.assertEqual(len(schedule["activities"]), 21)
            self.assertEqual(len(schedule["dependencies"]), 26)
            self.assertEqual(sorted(round(row["placed_concrete_m3"], 6)
                                    for row in schedule["element_quantities"]), [.544, .8, 2.4])
            proof = schedule["proof"]
            self.assertEqual(proof["project_makespan_minutes"], proof["lower_bound_minutes"])
            self.assertEqual(read("first", "round_trip.json")["original_instances_verified"], 73)
            folder = root / "first"
            data = workspace(folder)
            self.assertEqual({len(ids) for ids in data["viewer"]["activity_ids_by_element_global_id"].values()}, {7})
            self.verify_browser(data)
            tampered = folder / "viewer.json"
            tampered.write_bytes(tampered.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                workspace(folder)

    def verify_browser(self, data):
        from playwright.sync_api import sync_playwright
        with build_server(data, 0) as server, sync_playwright() as playwright:
            server_thread = Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            try:
                browser = playwright.chromium.launch(channel="msedge", args=[
                    "--enable-webgl", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
                ])
                page = browser.new_page(viewport={"width": 1550, "height": 1050})
                page.goto(f"http://127.0.0.1:{server.server_port}")
                page.wait_for_function("document.querySelector('#model').data?.length === 3")
                self.assertEqual(page.locator("#gantt .row").count(), 21)
                self.assertEqual(page.locator("#gantt .edge").count(), 26)
                page.locator("#gantt .row").first.press("Enter")
                self.assertEqual(page.locator("#elements button[aria-pressed=true]").count(), 1)
                page.locator("#elements button").first.click()
                self.assertEqual(page.locator("#gantt .row.related").count(), 7)
                page.locator("#cpm").click()
                self.assertGreater(page.locator("#gantt .bar.critical").count(), 0)
                page.locator("#cp_sat").click()
                page.locator("#scrub").evaluate("el => {el.value = el.max; el.dispatchEvent(new Event('input'));}")
                self.assertEqual(page.locator("#complete").inner_text(), "21 completed")
                browser.close()
            finally:
                server.shutdown()
                server_thread.join()


if __name__ == "__main__":
    unittest.main()
