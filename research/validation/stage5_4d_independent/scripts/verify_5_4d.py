"""Independent Stage 5.4D frontend verification (IFC interpreter, repo root).

    .venv/Scripts/python.exe -B research/validation/stage5_4d_independent/scripts/verify_5_4d.py

Oracles: the accepted Stage 5.4B.3 schedules (r0_{tick}_schedule.json), my own tessellation of the SOURCE IFC,
Python zoneinfo date formatting, and the server process itself for authentication and routing.
The browser is driven with Playwright (installed) and Microsoft Edge; Agent 1's verify_frontend.py is not used.
"""

import copy
import hashlib
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
REPO = HERE.parents[3]
IFCPY, PLAN = REPO / ".venv/Scripts/python.exe", REPO / ".venv-planning/Scripts/python.exe"
SOURCE = REPO / "research/implementation/stage5_2/controlled_frame.ifc"
ACC = REPO / "research/implementation/stage5_4b_integration"
CONFIG = ACC / "r0_config.json"
EDGE = r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
MADRID = ZoneInfo("Europe/Madrid")
CAT = {"productive": "Construction", "inspection": "Inspection", "elapsed_hold": "Curing hold", "strength_release": "Strength release"}

import ifcopenshell  # noqa: E402
import ifcopenshell.geom  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


def sha(b):
    return hashlib.sha256(b).hexdigest()


def fmt(iso):
    d = datetime.fromisoformat(iso).astimezone(MADRID)
    return d.strftime("%d %b, %H:%M")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def kill_tree(proc):
    """The venv python.exe is a launcher; terminate it together with the real interpreter it spawned."""
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)


def start_server(args, port):
    p = subprocess.Popen([str(IFCPY), "-B", "-m", "research.implementation.stage5_4d.server", *args, "--port", str(port)],
                         cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.time() + 120
    while time.time() < deadline:
        if p.poll() is not None:
            return p, False, (p.stderr.read() or p.stdout.read()).strip()[-200:]
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            return p, True, ""
        except OSError:
            time.sleep(0.3)
    kill_tree(p)
    return p, False, "timeout"


def http(port, path, method="GET"):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never route loopback via a system proxy
    try:
        with opener.open(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:  # noqa: BLE001
        return f"error:{type(e).__name__}", b""


def raw_http(port, line):
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(f"{line}\r\nHost: 127.0.0.1\r\n\r\n".encode())
    data = s.recv(200).decode(errors="replace")
    s.close()
    return data.split("\r\n", 1)[0]


def source_meshes():
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)
    out = {}
    model = ifcopenshell.open(str(SOURCE))  # keep the file alive while its elements are tessellated
    for e in model.by_type("IfcElement"):
        g = ifcopenshell.geom.create_shape(s, e).geometry
        out[e.GlobalId] = ([[round(v, 6) for v in g.verts[i:i + 3]] for i in range(0, len(g.verts), 3)],
                           [list(g.faces[i:i + 3]) for i in range(0, len(g.faces), 3)])
    return out


def check_data(data, tick):
    acc = json.loads((ACC / f"r0_{tick}_schedule.json").read_bytes())
    acts = {a["activity_id"]: a for a in acc["activities"]}
    v = data["viewer"]
    meshes = source_meshes()
    r = {
        "contract": data["contract_version"],
        "proof": data["proof"],
        "proof_matches_accepted": all(data["proof"][k] == acc["proof"][k] for k in data["proof"]),
        "elements": sorted(data["elements"]),
        "geometry_equals_source_tessellation": all(
            [[round(c, 6) for c in vert] for vert in data["elements"][g]["vertices"]] == meshes[g][0]
            and [list(f) for f in data["elements"][g]["faces"]] == meshes[g][1] for g in meshes) and set(meshes) == set(data["elements"]),
        "activities": len(v["activities_by_id"]),
        "dates_equal_accepted": all(
            (v["activities_by_id"][k]["cp_sat"]["start"], v["activities_by_id"][k]["cp_sat"]["finish"]) == (a["optimized"]["start"], a["optimized"]["finish"])
            and (v["activities_by_id"][k]["cpm"]["start"], v["activities_by_id"][k]["cpm"]["finish"]) == (a["baseline"]["start"], a["baseline"]["finish"])
            and v["activities_by_id"][k]["cpm"]["cpm_critical"] == a["baseline"]["cpm_critical"]
            for k, a in acts.items()),
        "element_links_equal_accepted": all(v["activities_by_id"][k]["element_global_ids"] == [a["ifc_global_id"]] for k, a in acts.items()),
        "dependencies_equal_accepted": {(d["predecessor_id"], d["successor_id"]) for d in v["dependencies"]}
        == {(d["predecessor_id"], d["successor_id"]) for d in acc["dependencies"]} and len(v["dependencies"]) == 28,
        "packages_equal_accepted": [(p["id"], p["activity_ids"]) for p in v["packages"]] == [(p["id"], p["activity_ids"]) for p in acc["work_packages"]],
        "status": {k: v["status"][k] for k in ("ApprovalStatus", "PendingApprovalCount", "RealProjectEligible")},
        "restriction": v["restriction"],
        "cpm_equals_cp_sat_all": all(a["optimized"]["start"] == a["baseline"]["start"] and a["optimized"]["finish"] == a["baseline"]["finish"] for a in acts.values()),
        "cpm_critical_ids": sorted(a["reference_id"] for a in acts.values() if a["baseline"]["cpm_critical"]),
    }
    return r, acc


def browser_checks(port, acc, tick, page, label):
    acts = {a["activity_id"]: a for a in acc["activities"]}
    deps = {(d["predecessor_id"], d["successor_id"]) for d in acc["dependencies"]}
    r = {}
    page.goto(f"http://127.0.0.1:{port}/")
    page.wait_for_function("document.querySelector('#model .gl-container canvas, #model canvas') !== null", timeout=60000)
    page.wait_for_timeout(1200)
    r["notice"] = page.inner_text(".notice")
    r["status_banner"] = page.inner_text(".status")
    r["playback_caption"] = page.inner_text(".simulation p")
    r["comparison_note"] = page.inner_text(".comparison")
    r["proof_text"] = page.inner_text("#proof")
    r["error_text"] = page.inner_text("#error")
    r["webgl_canvas"] = page.evaluate("!!document.querySelector('#model canvas') && document.getElementById('model').data.length")
    rows = page.evaluate("""() => [...document.querySelectorAll('#gantt g.row')].map(g => {
        const b = g.querySelector('rect.bar'); return {id: g.dataset.id, aria: g.getAttribute('aria-label'),
        x: +b.getAttribute('x'), w: +b.getAttribute('width'), y: +b.getAttribute('y'), cls: b.getAttribute('class')}; })""")
    r["rows"] = len(rows)
    edges = page.evaluate("() => [...document.querySelectorAll('#gantt path.edge')].map(p => p.getAttribute('d'))")
    r["edges"] = len(edges)
    b = min(datetime.fromisoformat(a["optimized"]["start"]) for a in acts.values()).timestamp()
    e = max(datetime.fromisoformat(a["optimized"]["finish"]) for a in acts.values()).timestamp()
    X = lambda iso: 192 + (datetime.fromisoformat(iso).timestamp() - b) / (e - b) * 670  # noqa: E731

    def label_ok(row, mode):
        a = acts[row["id"]]
        t = a["optimized"] if mode == "cp_sat" else a["baseline"]
        crit = mode == "cpm" and a["baseline"]["cpm_critical"]
        expected = f"{a['reference_id']} · {CAT[a['kind']]} · {fmt(t['start'])} – {fmt(t['finish'])}{' · CPM critical' if crit else ''}"
        geom = abs(row["x"] - X(t["start"])) < 1e-6 and abs(row["w"] - max(3, X(t["finish"]) - X(t["start"]))) < 1e-6
        return row["aria"] == expected and geom and (("critical" in row["cls"]) == crit)
    r["cp_sat_rows_dates_and_geometry_correct"] = all(label_ok(x, "cp_sat") for x in rows) and len(rows) == 21
    true_widths = {x["id"]: X(acts[x["id"]]["optimized"]["finish"]) - X(acts[x["id"]]["optimized"]["start"]) for x in rows}
    r["bars_widened_to_3px"] = sorted(acts[k]["reference_id"] for k, w in true_widths.items() if w < 3)
    r["bars_widened_detail"] = {acts[k]["reference_id"]: f"{(datetime.fromisoformat(acts[k]['optimized']['finish']) - datetime.fromisoformat(acts[k]['optimized']['start'])).total_seconds()/60:.0f} min shown as {3 * (e - b) / 670 / 60:.0f} min-equivalent"
                                for k, w in true_widths.items() if w < 3}
    # dependency arrows: start at predecessor finish x, end at successor start x, rows matched by y
    ymap = {round(x["y"] + 6, 3): x["id"] for x in rows}
    # app.js anchors arrows at the TRUE start/finish x, not at the 3-px widened bar end
    xs = {x["id"]: (X(acts[x["id"]]["optimized"]["start"]), X(acts[x["id"]]["optimized"]["finish"])) for x in rows}
    found = set()
    for d in edges:
        nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", d)]
        x0, y0, _, y1, x1 = nums[0], nums[1], nums[2], nums[3], nums[4]
        pid, sid = ymap.get(round(y0, 3)), ymap.get(round(y1, 3))
        if pid and sid and abs(x0 - xs[pid][1]) < 1e-6 and abs(x1 - xs[sid][0]) < 1e-6:
            found.add((pid, sid))
    r["arrows_match_dependencies_and_direction"] = found == deps
    # CPM mode
    page.click("#cpm")
    rows_cpm = page.evaluate("""() => [...document.querySelectorAll('#gantt g.row')].map(g => {
        const b = g.querySelector('rect.bar'); return {id: g.dataset.id, aria: g.getAttribute('aria-label'),
        x: +b.getAttribute('x'), w: +b.getAttribute('width'), y: +b.getAttribute('y'), cls: b.getAttribute('class')}; })""")
    r["cpm_rows_dates_geometry_and_critical_correct"] = all(label_ok(x, "cpm") for x in rows_cpm) and len(rows_cpm) == 21
    r["cpm_critical_rows"] = sorted(acts[x["id"]]["reference_id"] for x in rows_cpm if "critical" in x["cls"])
    r["cpm_bar_geometry_identical_to_cp_sat"] = [(x["x"], x["w"]) for x in rows_cpm] == [(x["x"], x["w"]) for x in rows]
    page.click("#cp_sat")
    # element selection (keyboard-accessible buttons) -> 7 related rows
    sel = {}
    for gid in sorted({a["ifc_global_id"] for a in acts.values()}):
        page.click(f"#elements button[data-gid='{gid}']")
        related = page.evaluate("() => [...document.querySelectorAll('#gantt g.row.related')].map(g => g.dataset.id)")
        sel[gid] = sorted(related) == sorted(k for k, a in acts.items() if a["ifc_global_id"] == gid) and len(related) == 7 \
            and gid in page.inner_text("#identity")
    r["element_to_activities"] = sel
    # activity selection -> element highlight (click and keyboard)
    ok = True
    for i, k in enumerate(acts):
        if i % 2:
            page.click(f"#gantt g.row[data-id='{k}']")
        else:
            page.focus(f"#gantt g.row[data-id='{k}']")
            page.keyboard.press("Enter")
        pressed = page.evaluate("() => [...document.querySelectorAll('#elements button[aria-pressed=\"true\"]')].map(b => b.dataset.gid)")
        a = acts[k]
        detail = page.inner_text("#activity")
        ok &= pressed == [a["ifc_global_id"]] and f"{fmt(a['optimized']['start'])} – {fmt(a['optimized']['finish'])} CET" in detail
    r["activity_to_element_all_21"] = ok
    page.click("#clear")
    # real 3D picking: scan canvas for hover targets, then click
    page.evaluate("""() => { window.__hover = null; document.getElementById('model').on('plotly_hover', e => { window.__hover = e.points[0].curveNumber; }); }""")
    box = page.locator("#model").bounding_box()
    hits = {}
    for gy in range(4, 97, 3):
        for gx in range(4, 97, 3):
            px, py = box["x"] + box["width"] * gx / 100, box["y"] + box["height"] * gy / 100
            page.evaluate("() => { window.__hover = null; }")
            page.mouse.move(px, py)
            page.wait_for_timeout(20)
            c = page.evaluate("() => window.__hover")
            if c is not None:
                hits.setdefault(c, []).append((px, py))
    picked, attempts = {}, {}
    traces = page.evaluate("() => document.getElementById('model').data.map(t => t.meta)")
    for c, plist in hits.items():
        # interior candidates: points nearest the middle of this element's hover footprint
        mx = sorted(p[0] for p in plist)[len(plist) // 2]
        my = sorted(p[1] for p in plist)[len(plist) // 2]
        candidates = sorted(plist, key=lambda p: (p[0] - mx) ** 2 + (p[1] - my) ** 2)[:5]
        tries = []
        for px, py in candidates:
            page.click("#clear")
            page.mouse.move(px, py)
            page.wait_for_timeout(200)
            page.mouse.down()
            page.wait_for_timeout(120)
            page.mouse.up()
            page.wait_for_timeout(250)
            pressed = page.evaluate("() => [...document.querySelectorAll('#elements button[aria-pressed=\"true\"]')].map(b => b.dataset.gid)")
            related = page.evaluate("() => document.querySelectorAll('#gantt g.row.related').length")
            tries.append(pressed[0] if pressed else None)
            if pressed:
                break
        attempts[traces[c]] = tries
        picked[traces[c]] = bool(tries) and tries[-1] == traces[c] and related == 7 and all(t in (None, traces[c]) for t in tries)
    r["real_canvas_picking_attempts"] = attempts
    r["real_canvas_picking"] = picked
    page.click("#clear")
    # camera: zoom, reset, orbit drag, pan drag
    eye = lambda: page.evaluate("() => document.getElementById('model').layout.scene.camera.eye")  # noqa: E731
    e0 = eye()
    page.click("#zoom-in")
    page.wait_for_timeout(200)
    e1 = eye()
    page.click("#zoom-out")
    page.wait_for_timeout(200)
    cx, cy = box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.85
    page.mouse.move(cx, cy)
    page.wait_for_timeout(150)
    page.mouse.down()
    page.wait_for_timeout(100)
    page.mouse.move(cx + 140, cy - 50, steps=20)
    page.wait_for_timeout(100)
    page.mouse.up()
    page.wait_for_timeout(700)
    e2 = eye()
    center0 = page.evaluate("() => document.getElementById('model').layout.scene.camera.center || {x:0,y:0,z:0}")
    page.evaluate("() => Plotly.relayout(document.getElementById('model'), {'scene.dragmode': 'pan'})")
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.move(cx + 80, cy - 30, steps=8)
    page.mouse.up()
    page.wait_for_timeout(300)
    center1 = page.evaluate("() => document.getElementById('model').layout.scene.camera.center")
    page.mouse.move(cx, cy)
    page.mouse.wheel(0, -400)
    page.wait_for_timeout(300)
    e3 = eye()
    page.click("#reset")
    page.wait_for_timeout(300)
    e4 = eye()
    r["camera"] = {"zoom_in_scales_0_82": all(abs(e1[k] - e0[k] * 0.82) < 1e-6 for k in "xyz"),
                   "orbit_drag_changes_eye": any(abs(e2[k] - e0[k]) > 1e-3 for k in "xyz"),
                   "pan_drag_changes_center": center1 is not None and any(abs(center1[k] - center0.get(k, 0)) > 1e-4 for k in "xyz"),
                   "wheel_zoom_changes_distance": abs(sum(v * v for v in e3.values()) - sum(v * v for v in e0.values())) > 1e-3,
                   "reset_restores_initial": all(abs(e4[k] - {"x": 1.45, "y": -1.7, "z": 1.25}[k]) < 1e-9 for k in "xyz")}
    # package filter
    filt = {}
    for p in acc["work_packages"]:
        page.select_option("#package", p["id"])
        ids = page.evaluate("() => [...document.querySelectorAll('#gantt g.row')].map(g => g.dataset.id)")
        n_edges = page.evaluate("() => document.querySelectorAll('#gantt path.edge').length")
        inside = sum(1 for a, s in deps if a in p["activity_ids"] and s in p["activity_ids"])
        filt[p["family"]] = sorted(ids) == sorted(p["activity_ids"]) and n_edges == inside
    page.select_option("#package", "")
    r["package_filter"] = filt
    # playback: scrub to sampled instants and compare counts with the accepted schedule
    total = (e - b) / 60
    samples = sorted({0, 30, 120, 1440, 2000, 5000, 9000, 14000, int(total) - 15, int(total)})
    counts_ok, examples = True, []
    for m in samples:
        page.evaluate(f"() => {{ const s = document.getElementById('scrub'); s.value = {m}; s.dispatchEvent(new Event('input')); }}")
        t = b + m * 60
        act = sum(1 for a in acts.values() if any(datetime.fromisoformat(x).timestamp() <= t < datetime.fromisoformat(y).timestamp() for x, y in a["optimized"]["segments"]))
        comp = sum(1 for a in acts.values() if t >= datetime.fromisoformat(a["optimized"]["finish"]).timestamp())
        shown = (page.inner_text("#active"), page.inner_text("#complete"), page.inner_text("#date"))
        exp_date = datetime.fromtimestamp(t, MADRID).strftime("%d %b, %H:%M") + " CET"
        good = shown == (f"{act} active", f"{comp} completed", exp_date)
        counts_ok &= good
        examples.append({"minute": m, "shown": shown, "expected": (act, comp, exp_date), "ok": good})
    r["scrub_counts_and_dates"] = counts_ok
    r["scrub_examples"] = examples[:4] + examples[-2:]
    r["scrub_max_equals_makespan"] = int(page.get_attribute("#scrub", "max")) == acc["proof"]["project_makespan_minutes"]
    # play / pause / speed
    page.evaluate("() => { const s = document.getElementById('scrub'); s.value = 0; s.dispatchEvent(new Event('input')); }")
    page.select_option("#speed", "5")
    page.click("#play")
    page.wait_for_timeout(1500)
    page.click("#play")
    v1 = int(page.get_attribute("#scrub", "value") or 0) if False else page.evaluate("() => +document.getElementById('scrub').value")
    page.wait_for_timeout(700)
    v2 = page.evaluate("() => +document.getElementById('scrub').value")
    page.select_option("#speed", "0.5")
    page.click("#play")
    page.wait_for_timeout(1500)
    page.click("#play")
    v3 = page.evaluate("() => +document.getElementById('scrub').value")
    r["playback"] = {"advanced_at_5x_in_1_5s": v1, "paused_stays": v1 == v2, "advanced_at_0_5x_in_1_5s": v3 - v2,
                     "speed_ratio_plausible": 4 < v1 / max(1, (v3 - v2)) < 20, "label_after_pause": page.inner_text("#play")}
    page.evaluate(f"() => {{ const s = document.getElementById('scrub'); s.value = {int(total)}; s.dispatchEvent(new Event('input')); }}")
    colors = page.evaluate("() => document.getElementById('model').data.map(t => t.color)")
    r["end_state"] = {"complete_text": page.inner_text("#complete"), "element_colors": colors,
                      "all_green": all(c == "#4e9a78" for c in colors)}
    return r


def main():
    result = {"head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()}
    before = {p.name: sha(p.read_bytes()) for p in sorted((REPO / "research/implementation/stage5_4d").rglob("*")) if p.is_file()}
    tmp = Path(tempfile.mkdtemp(prefix="pmi_54d_"))
    port = 8791
    try:
        # live application bundle
        live = tmp / "live5"
        lp = subprocess.run([str(PLAN), "-B", "-m", "pmi_core.application", "--config", str(CONFIG), "--output", str(live),
                             "--tick", "5", "--ifc4d", "--ifc-python", str(IFCPY), "--planning-python", str(PLAN)],
                            cwd=REPO, capture_output=True, text=True)
        result["live_run_exit"] = lp.returncode
        result["live_run_stderr_tail"] = lp.stderr[-300:]
        sources = [("replay_5", ["--tick", "5"], 5), ("replay_15", ["--tick", "15"], 15), ("live_5", ["--run-dir", str(live)], 5)]
        result["workspaces"] = {}
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=EDGE)
            for name, args, tick in sources:
                port = free_port()
                proc, ok, msg = start_server(args, port)
                entry = {"server_started": ok, "message": msg}
                try:
                    if ok:
                        status, body = http(port, "/data.json")
                        data = json.loads(body)
                        entry["data"], acc = check_data(data, tick)
                        tz_results = {}
                        for tz in ("Europe/Madrid", "America/New_York", "Asia/Tokyo"):
                            ctx = browser.new_context(timezone_id=tz, viewport={"width": 1500, "height": 1000})
                            page = ctx.new_page()
                            errors = []
                            page.on("pageerror", lambda ex: errors.append(str(ex)))
                            if tz == "Europe/Madrid":
                                entry["browser"] = browser_checks(port, acc, tick, page, name)
                                shot = OUT / f"screenshot_{name}.png"
                                page.evaluate("() => { const s = document.getElementById('scrub'); s.value = 5000; s.dispatchEvent(new Event('input')); }")
                                page.click(f"#elements button[data-gid='1jDfy2_jTRueAw6f5fc3Ev']")
                                page.screenshot(path=str(shot), full_page=True)
                            else:
                                page.goto(f"http://127.0.0.1:{port}/")
                                page.wait_for_selector("#gantt g.row")
                                first = page.evaluate("() => document.querySelector('#gantt g.row').getAttribute('aria-label')")
                                acts = {a["activity_id"]: a for a in acc["activities"]}
                                fid = page.evaluate("() => document.querySelector('#gantt g.row').dataset.id")
                                tz_results[tz] = fmt(acts[fid]["optimized"]["start"]) in first
                            entry.setdefault("page_errors", {})[tz] = errors
                            ctx.close()
                        entry["browser_timezone_independent_labels"] = tz_results
                        # routes
                        routes = {}
                        for path in ("/", "/style.css", "/app.js", "/plotly.js", "/data.json", "/index.html", "/server.py",
                                     "/../server.py", "/%2e%2e/server.py", "/data.json?x=1", "//etc/passwd", "/README.md",
                                     "/research/implementation/stage5_2/controlled_frame.ifc", "/scheduled.ifc", "/ifc4d/scheduled.ifc"):
                            routes[path] = http(port, path)[0]
                        routes["POST /data.json"] = http(port, "/data.json", "POST")[0]
                        routes["PUT /"] = http(port, "/", "PUT")[0]
                        routes["raw GET absolute-form"] = raw_http(port, "GET http://127.0.0.1/../../server.py HTTP/1.1")
                        routes["raw GET backslash"] = raw_http(port, "GET /..\\..\\server.py HTTP/1.1")
                        lan = None
                        try:
                            ip = socket.gethostbyname(socket.gethostname())
                            socket.create_connection((ip, port), timeout=1).close()
                            lan = f"reachable on {ip}"
                        except OSError:
                            lan = "not reachable on LAN address"
                        routes["non-loopback"] = lan
                        entry["routes"] = routes
                finally:
                    kill_tree(proc)
                result["workspaces"][name] = entry
            browser.close()
        # ---- tampered bundles: the server must refuse to start
        def variant(name, fn):
            d = tmp / name
            shutil.copytree(live, d)
            fn(d)
            return d

        def edit_json(path, fn):
            obj = json.loads(path.read_bytes())
            fn(obj)
            path.write_bytes(json.dumps(obj, indent=2).encode())

        def shift(s):
            last = max(s["activities"], key=lambda a: a["optimized"]["finish"])
            last["optimized"]["finish"] = last["optimized"]["finish"].replace("T", "T")
            last["reference_id"] = last["reference_id"] + "-X"

        def resync_digest(d):
            ev = json.loads((d / "pipeline_evidence.json").read_bytes())
            ev["stage_payload_sha256"]["schedule"] = sha((d / "schedule.json").read_bytes())
            (d / "pipeline_evidence.json").write_bytes(json.dumps(ev, indent=2).encode())

        cases = {
            "modified schedule (label) with resynced digest": variant("t1", lambda d: (edit_json(d / "schedule.json", shift), resync_digest(d))),
            "modified schedule date with resynced digest": variant("t2", lambda d: (edit_json(d / "schedule.json", lambda s: s["activities"][-1]["optimized"].update(
                finish=s["activities"][-1]["optimized"]["finish"][:11] + "15:55" + s["activities"][-1]["optimized"]["finish"][16:])), resync_digest(d))),
            "modified IFC bytes": variant("t3", lambda d: (d / "ifc4d/scheduled.ifc").write_bytes((d / "ifc4d/scheduled.ifc").read_bytes().replace(b"ENDSEC;", b"/*x*/ENDSEC;", 1))),
            "modified viewer contract": variant("t4", lambda d: edit_json(d / "ifc4d/viewer.json", lambda v: v["activities_by_id"][next(iter(v["activities_by_id"]))].update(label="X"))),
            "altered IFC + updated viewer and round-trip hashes": variant("t5", lambda d: (
                (d / "ifc4d/scheduled.ifc").write_bytes((d / "ifc4d/scheduled.ifc").read_bytes().replace(b"ENDSEC;", b"/*x*/ENDSEC;", 1)),
                edit_json(d / "ifc4d/viewer.json", lambda v: v["model"].update(sha256=sha((d / "ifc4d/scheduled.ifc").read_bytes()))),
                edit_json(d / "ifc4d/round_trip.json", lambda r: r.update(output_ifc_sha256=sha((d / "ifc4d/scheduled.ifc").read_bytes()))))),
            "changed engineering approval with resynced digest": variant("t6", lambda d: (edit_json(d / "schedule.json", lambda s: s["pending_approvals"][0].update(status="APPROVED")), resync_digest(d))),
            "unsupported IFC model in bundle": variant("t7", lambda d: shutil.copyfile(REPO / "research/implementation/stage5_2/controlled_frame.ifc", d / "ifc4d/scheduled.ifc")),
            "missing pipeline evidence": variant("t8", lambda d: (d / "pipeline_evidence.json").unlink()),
        }
        c01 = tmp / "c01"
        c01.mkdir()
        shutil.copyfile(ACC / "original_v1.1_schedule.json", c01 / "schedule.json")
        (c01 / "pipeline_evidence.json").write_text(json.dumps({"stage_payload_sha256": {"schedule": sha((c01 / "schedule.json").read_bytes())}}))
        cases["C01 benchmark as run directory"] = c01
        neg = {}
        for name, d in cases.items():
            port = free_port()
            proc, ok, msg = start_server(["--run-dir", str(d)], port)
            if ok:
                kill_tree(proc)
            neg[name] = {"refused": not ok, "message": msg[-150:]}
        for name, args in (("unregistered tick 10", ["--tick", "10"]),):
            port = free_port()
            proc, ok, msg = start_server(args, port)
            if ok:
                kill_tree(proc)
            neg[name] = {"refused": not ok, "message": msg[-120:]}
        result["negative"] = neg
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    after = {p.name: sha(p.read_bytes()) for p in sorted((REPO / "research/implementation/stage5_4d").rglob("*")) if p.is_file()}
    result["stage5_4d_files_stable"] = before == after
    (OUT / "independent_frontend_results.json").write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1, default=str)[:20000])


if __name__ == "__main__":
    main()
