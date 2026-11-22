"""Verify controlled inputs and browser interactions, optionally capturing evidence."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from threading import Thread

from playwright.sync_api import sync_playwright

from research.implementation.stage5_4d.server import (
    ELEMENTS, ROOT, SCHEDULES, SOURCE, build_server, load_workspace, meshes,
)


def reject(run):
    try:
        load_workspace(run_dir=run)
    except (OSError, ValueError, KeyError) as error:
        return str(error)
    raise AssertionError("Unsupported bundle was accepted")


def verify_loading():
    with TemporaryDirectory(prefix="pmi-r0-check-") as directory:
        temp = Path(directory)
        for tick, expected in ((5, 14850), (15, 14880)):
            replay = load_workspace(tick=tick)
            run = temp / str(tick)
            subprocess.run([
                str(ROOT / ".venv-planning/Scripts/python.exe"), "-B", "-m", "pmi_core.application",
                "--config", str(SCHEDULES / "r0_config.json"), "--output", str(run),
                "--ifc-python", str(ROOT / ".venv/Scripts/python.exe"),
                "--planning-python", str(ROOT / ".venv-planning/Scripts/python.exe"),
                "--tick", str(tick), "--ifc4d",
            ], cwd=ROOT, check=True, capture_output=True, text=True)
            live = load_workspace(run_dir=run)
            assert live["elements"] == replay["elements"] == meshes(SOURCE)
            assert set(live["elements"]) == ELEMENTS
            assert live["proof"]["project_makespan_minutes"] == live["proof"]["lower_bound_minutes"] == expected
            viewer = live["viewer"]
            assert len(viewer["packages"]) == 3 and len(viewer["dependencies"]) == 28
            assert viewer["status"]["PendingApprovalCount"] == 88
            assert viewer["status"]["RealProjectEligible"] is False
            assert len(viewer["activities_by_id"]) == 21
            for gid, ids in viewer["activity_ids_by_element_global_id"].items():
                assert len(set(ids)) == 7
                assert all(viewer["activities_by_id"][key]["element_global_ids"] == [gid] for key in ids)
            print(f"R0 {tick} minutes: authenticated live/replay, 3 meshes, 21 links, 28 edges")

        live_path = temp / "5"
        tampered = temp / "tampered"
        shutil.copytree(live_path, tampered)
        pipeline = tampered / "pipeline_evidence.json"
        original_pipeline = pipeline.read_bytes()
        pipeline.unlink()
        assert "pipeline_evidence.json" in reject(tampered)
        pipeline.write_bytes(original_pipeline)

        bundle = tampered / "ifc4d"
        ifc = bundle / "scheduled.ifc"
        original_ifc = ifc.read_bytes()
        ifc.write_bytes((ROOT / "models/test_case/original.ifc").read_bytes())
        viewer_path = bundle / "viewer.json"
        original_viewer = viewer_path.read_bytes()
        changed = json.loads(original_viewer)
        changed["model"]["sha256"] = sha256(ifc.read_bytes()).hexdigest()
        viewer_path.write_text(json.dumps(changed), encoding="utf-8")
        assert "scheduled.ifc" in reject(tampered)
        ifc.write_bytes(original_ifc)
        assert "viewer.json" in reject(tampered)
        viewer_path.write_bytes(original_viewer)

        schedule_path = tampered / "schedule.json"
        forged = json.loads(schedule_path.read_bytes())
        forged["cost"]["total_direct_reference_eur"] += 1
        schedule_path.write_text(json.dumps(forged), encoding="utf-8")
        evidence = json.loads(original_pipeline)
        evidence["stage_payload_sha256"]["schedule"] = sha256(schedule_path.read_bytes()).hexdigest()
        pipeline.write_text(json.dumps(evidence), encoding="utf-8")
        assert "content or provenance differs" in reject(tampered)

        schedule_path.write_bytes((SCHEDULES / "original_v1.1_schedule.json").read_bytes())
        reject(tampered)
        print("Rejected missing evidence, substituted IFC, modified viewer, rehashed schedule forgery and C01")


def verify_browser(edge, screenshots):
    workspace = load_workspace()
    with build_server(workspace, 0) as server, sync_playwright() as playwright:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        browser = None
        try:
            browser = playwright.chromium.launch(executable_path=str(edge), args=[
                "--enable-webgl", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
            ])
            page = browser.new_page(viewport={"width": 1570, "height": 1150})
            page.set_default_timeout(8000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}")
            page.wait_for_function("document.querySelector('#model')._fullLayout?.scene?._scene?.glplot")
            assert page.locator("#gantt .row").count() == 21
            assert page.locator("#gantt .edge").count() == 28
            assert "88 pending" in page.locator("header").inner_text()
            assert "NOT AUTHORIZED FOR CONSTRUCTION USE" in page.locator(".notice").inner_text()
            model = page.locator("#model")
            camera_before = model.evaluate("el => el._fullLayout.scene.camera.eye")
            box = model.bounding_box()
            page.mouse.move(box["x"] + box["width"] * .48, box["y"] + box["height"] * .52)
            page.mouse.down()
            page.mouse.move(box["x"] + box["width"] * .62, box["y"] + box["height"] * .58, steps=9)
            page.mouse.up()
            page.wait_for_function("""initial => {
                const eye = document.querySelector('#model')._fullLayout.scene.camera.eye;
                return Math.abs(eye.x - initial.x) > .01 || Math.abs(eye.y - initial.y) > .01;
            }""", arg=camera_before)
            page.locator("#reset").click()
            page.wait_for_function("""initial => {
                const eye = document.querySelector('#model')._fullLayout.scene.camera.eye;
                return Math.abs(eye.x - initial.x) < .01 && Math.abs(eye.y - initial.y) < .01;
            }""", arg=camera_before)
            page.locator("#zoom-in").click()
            page.wait_for_function("""initial => {
                const eye = document.querySelector('#model')._fullLayout.scene.camera.eye;
                return Math.abs(Math.hypot(eye.x, eye.y, eye.z) -
                    Math.hypot(initial.x, initial.y, initial.z)) > .02;
            }""", arg=camera_before)
            page.locator("#reset").click()
            model.locator('[data-title="Pan"]').click()
            camera_center = model.evaluate("el => el._fullLayout.scene.camera.center")
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.mouse.down()
            page.mouse.move(box["x"] + box["width"] * .62, box["y"] + box["height"] * .58, steps=9)
            page.mouse.up()
            page.wait_for_function("""initial => {
                const center = document.querySelector('#model')._fullLayout.scene.camera.center;
                return Math.hypot(center.x - initial.x, center.y - initial.y, center.z - initial.z) > .02;
            }""", arg=camera_center)
            page.locator("#reset").click()

            row = page.locator("#gantt .row").first
            row.press("Enter")
            assert page.locator("#gantt .row.selected").count() == 1
            gid = page.locator("#elements button[aria-pressed=true]").get_attribute("data-gid")
            assert gid in ELEMENTS and gid in page.locator("#identity").inner_text()
            assert page.locator("#gantt .row.related").count() == 7
            page.locator("#cpm").click()
            assert page.locator("#gantt .bar.critical").count() > 0
            cpm = page.locator("#gantt .bar").evaluate_all("els => els.map(e => [e.getAttribute('x'),e.getAttribute('width')])")
            page.locator("#cp_sat").click()
            cp_sat = page.locator("#gantt .bar").evaluate_all("els => els.map(e => [e.getAttribute('x'),e.getAttribute('width')])")
            assert cpm == cp_sat
            assert "coincide" in page.locator(".comparison").inner_text()

            page.locator("#clear").click()
            page.evaluate("""() => {
                window.meshHover = null;
                document.querySelector('#model').on('plotly_hover', event => {
                    window.meshHover = event.points[0]?.curveNumber;
                }).on('plotly_unhover', () => { window.meshHover = null; });
            }""")
            # Click the slab face at the fixed default camera and viewport.
            box = model.bounding_box()
            for dx, dy in ((.50, .31), (.43, .32), (.36, .36), (.29, .46)):
                page.mouse.move(box["x"] + box["width"] * dx, box["y"] + box["height"] * dy)
                page.wait_for_timeout(100)
                page.mouse.down()
                page.wait_for_timeout(100)
                page.mouse.up()
                if page.locator("#elements button[aria-pressed=true]").count():
                    break
            assert page.locator("#elements button[aria-pressed=true]").count() == 1, (
                f"3D pointer selection failed, hover trace: {page.evaluate('window.meshHover')}")
            assert page.locator("#gantt .row.related").count() == 7
            page.mouse.move(10, 100)
            if screenshots:
                screenshots.mkdir(exist_ok=True, parents=True)
                page.screenshot(path=screenshots / "r0-overview.png", full_page=True)

            picked = page.locator("#elements button[aria-pressed=true]").get_attribute("data-gid")
            viewer = workspace["viewer"]
            first_link = viewer["activity_ids_by_element_global_id"][picked][0]
            package = viewer["activities_by_id"][first_link]["package_id"]
            page.locator("#package").select_option(value=package)
            assert page.locator("#gantt .row.related").count() == 7
            scrub = page.locator("#scrub")
            scrub.evaluate("el => { el.value = 3000; el.dispatchEvent(new Event('input')); }")
            date = page.locator("#date").inner_text()
            page.locator("#speed").select_option("5")
            page.locator("#play").click()
            page.wait_for_function("Number(document.querySelector('#scrub').value) > 3050")
            page.locator("#play").click()
            assert page.locator("#play").inner_text() == "Play"
            assert page.locator("#date").inner_text() != date
            if screenshots:
                page.screenshot(path=screenshots / "r0-playback.png", full_page=True)
            scrub.evaluate("el => { el.value = el.max; el.dispatchEvent(new Event('input')); }")
            assert page.locator("#complete").inner_text() == "21 completed"
            assert page.locator("#active").inner_text() == "0 active"
            assert not errors, errors
            print("Browser: WebGL, orbit/zoom/pan/reset, direct 3D picking, keyboard Gantt selection, filter, CPM and playback passed")
        finally:
            if browser is not None:
                browser.close()
            server.shutdown()
            thread.join()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edge", type=Path, default=Path(
        "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"))
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    verify_loading()
    verify_browser(args.edge, args.screenshots)


if __name__ == "__main__":
    main()
