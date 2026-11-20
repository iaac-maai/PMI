"""Generate integration evidence without writing to the accepted baseline or reference packages."""
import csv
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from pmi_core.application import run_controlled_pipeline
from pmi_core.schedule_result import schedule_result
from research.implementation.stage5_4b.demo import CORRECTION, benchmark_path
from research.implementation.stage5_4b.fixtures import REFERENCES, ROOT
from .test_integration import F01, split_case
from research.implementation.stage5_4b.engine import solve


OUT = Path(__file__).resolve().parent
BASE = "cf8f4581e65e027cd843ed42c81384a5d60224ef"
IFC = ROOT / ".venv/Scripts/python.exe"
PLANNING = ROOT / ".venv-planning/Scripts/python.exe"
COLLECT = """import json
from research.implementation.stage5_4b.fixtures import reference_cases, normalize_reference, frozen_r0
from research.implementation.stage5_4b.demo import construction_demo
from research.implementation.stage5_4b.engine import solve
out = {k: solve(normalize_reference(c)) for k,c in reference_cases().items() if k != 'DEMO-H1'}
for t in (5,15): out['frozen_R0_'+str(t)] = solve(frozen_r0(t))
for h,name in ((False,'original'),(True,'holiday')):
 for version in ('v1.0','v1.1'):
  out[name+'_'+version] = solve(construction_demo(h,version=version),time_limit=20)
print(json.dumps(out))
"""


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def call(exe, *args, cwd=ROOT, env=None):
    cmd = [str(exe), *map(str,args)]
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, encoding="utf-8", errors="replace", env=env)
    if result.returncode:
        raise RuntimeError(f"{cmd}: {result.returncode}\n{result.stdout}\n{result.stderr}")
    return result


def occupancy(rows):
    # Capacity allowances subdivide a working interval without changing its total duration.
    from datetime import datetime
    from collections import Counter
    result = Counter()
    for row in rows:
        if row["occupancy_basis"] == "continuous_elapsed":
            continue
        minutes = int((datetime.fromisoformat(row["finish"]) - datetime.fromisoformat(row["start"])).total_seconds() / 60)
        result[(row["holder_id"], row["resource_id"], row["demand"])] += minutes
    return result


def compare(old, new):
    rows = []
    for key, before in old.items():
        after = new[key]
        fields = ("status", "solver_status", "solver_scope", "objective_minutes", "lower_bound_minutes",
                  "optimality_gap_minutes", "cost", "real_project_eligible", "pending_approvals",
                  "fixture_exceptions", "blocked_activities", "conditional_activities")
        same = all(before.get(name) == after.get(name) for name in fields)
        code = lambda row: (row.get("diagnostic") or {}).get("code")
        provenance = lambda row: {a["id"]: (a.get("input_state"), a.get("crew_mode"),
                                            a.get("pending_approval_ids"), a.get("reference_cost_eur"))
                                  for a in row["activities"]}
        quantities = lambda row: {r["reservation_id"]: (r["resource_id"], r["quantity"])
                                  for r in row.get("reservations", [])}
        equivalent = (same and before["validated"] == after["validated"] and code(before) == code(after)
                      and provenance(before) == provenance(after) and quantities(before) == quantities(after)
                      and occupancy(before.get("resource_occupancy", [])) == occupancy(after.get("resource_occupancy", [])))
        dates = lambda row: {a["id"]: (a["start"], a["finish"], a["segments"]) for a in row["activities"]}
        rows.append({"case": key, "baseline_status": before["status"], "relocated_status": after["status"],
                     "objective_minutes": after["objective_minutes"], "lower_bound_minutes": after["lower_bound_minutes"],
                     "diagnostic_code": code(after), "validated": after["validated"],
                     "representative_timestamps_identical": dates(before) == dates(after),
                     "equivalent": equivalent})
    assert len(rows) == 36 and all(row["equivalent"] for row in rows), [r for r in rows if not r["equivalent"]]
    with (OUT / "behavioural_equivalence_results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


def main():
    tests = {}
    modules = [f"research.implementation.stage5_4b.test_{s}" for s in ("engine", "advanced", "review", "closure")]
    for key, exe, args in (
        ("historical", IFC, ["discover", "-s", "tests", "-p", "test_stage5_*.py"]),
        ("optimizer_and_integration", PLANNING, modules + ["research.implementation.stage5_4b_integration.test_integration"]),
    ):
        report = call(exe, "-B", "-m", "unittest", *args)
        tests[key] = {"python": str(exe), "tests_run": int(re.search(r"Ran (\d+) tests", report.stderr)[1]),
                      "exit_code": report.returncode, "summary": report.stderr.strip()}
    with TemporaryDirectory(prefix="pmi-integration-") as home:
        temp = Path(home)
        archive = subprocess.check_output(["git", "archive", "--format=zip", BASE, "pmi_core",
                                           "research/implementation/stage5_4a", "research/implementation/stage5_4b",
                                           "research/implementation/stage5_3", "research/planning/stage5_4_preparation",
                                           "research/validation/engineering_approval_review",
                                           "research/validation/stage5_4a_independent_verification"], cwd=ROOT)
        baseline = temp / "baseline"
        with ZipFile(BytesIO(archive)) as saved:
            saved.extractall(baseline)
        # Git's archive text conversion can differ from the project checkout.
        # Reproduce checkout bytes only where CRLF normalization proves identity.
        for saved in baseline.rglob("*"):
            if not saved.is_file():
                continue
            live = ROOT / saved.relative_to(baseline)
            if not live.is_file():
                continue
            a, b = saved.read_bytes(), live.read_bytes()
            if a != b and a.replace(b"\r\n", b"\n") == b.replace(b"\r\n", b"\n"):
                saved.write_bytes(b)
        before = json.loads(call(PLANNING, "-B", "-c", COLLECT, cwd=baseline).stdout)
        after = json.loads(call(PLANNING, "-B", "-c", COLLECT).stdout)
        compare(before, after)

        end = {"r0": {}, "benchmarks": {}}
        for tick in (5, 15):
            output = temp / f"r0_{tick}"
            schedule = run_controlled_pipeline(OUT / "r0_config.json", output=output, ifc_python=IFC,
                                               planning_python=PLANNING, tick=tick, root=ROOT)
            assert schedule["proof"]["project_makespan_minutes"] == {5: 14850, 15: 14880}[tick]
            assert schedule["cost"]["total_direct_reference_eur"] == 1172.5136
            key = f"r0_{tick}_schedule.json"
            write(OUT / key, schedule)
            end["r0"][str(tick)] = {"schedule": key, "proof": schedule["proof"], "cost": schedule["cost"],
                                     "source_ifc_sha256": schedule["source_ifc_sha256"], "evidence": schedule["evidence"]}
        for holiday, name in ((False, "original"), (True, "holiday")):
            for version in ("v1.0", "v1.1"):
                key = f"{name}_{version}"
                result = after[key]
                path = benchmark_path(holiday, version)
                raw = read(path)
                evidence = {"fixture_relative_path": path.relative_to(ROOT).as_posix(),
                            "fixture_sha256": sha256(path.read_bytes()).hexdigest(), "geometry": "not_supplied"}
                unified = schedule_result(optimized=result, provenance=evidence, project_id=raw["project"]["id"],
                                          engineering={a["id"]: a for a in raw["activities"]},
                                          activity_metadata={a["id"]: a for a in raw["activities"]})
                filename = f"{key}_schedule.json"
                # Keep the compact v1.0 negative results and complete v1.1 schedules.
                write(OUT / filename, unified)
                end["benchmarks"][key] = {"schedule": filename, "proof": unified["proof"],
                                         "diagnostic": unified["diagnostic"], "cost": unified["cost"],
                                         "resource_conflicts": len(unified["resource_conflicts"]) if result["validated"] else None,
                                         "evidence": evidence}
        write(OUT / "end_to_end_results.json", end)
        c01 = str(CORRECTION / "scripts/correct_and_verify.py")
        oracle_code = """import json, runpy, sys
from pathlib import Path
ns = runpy.run_path(sys.argv[1])
root = Path(sys.argv[2])
for label in ('original','holiday'):
    schedule = json.loads((root/f'{label}_v1.1_schedule.json').read_text(encoding='utf-8'))
    fixture = ns['load'](Path(schedule['evidence']['fixture_relative_path']))
    ns['b'].DATE_EXCEPTIONS = fixture['calendars'][0]['date_exceptions']
    timings = {a['activity_id']:(a['optimized']['start'],a['optimized']['finish']) for a in schedule['activities']}
    checks = ns['check_with_coverage'](fixture,timings)
    assert len(checks) == 350 and all(c['passed'] for c in checks),label
"""
        call(IFC, "-B", "-c", oracle_code, c01, OUT, env=dict(os.environ, PYTHONHASHSEED="0"))
        tests["independent_c01"] = {"passed_checks_per_fixture": 350, "fixtures": 2}

        f01 = {}
        for variant in ("A_restart_30", "B_restart_0"):
            result = solve(split_case(variant))
            write(temp / f"{variant}.json", result)
            f01[variant] = {key: result[key] for key in ("objective_minutes", "cost", "supply_totals",
                                                       "supply_checks", "supply_by_activity", "supply_by_source")}
        field_map = {"placed_volume": "aggregate_planned_placed_volume_m3",
                     "restart_allowance": "aggregate_restart_capacity_allowance_m3",
                     "total_allowance": "aggregate_total_capacity_allowance_m3",
                     "occupancy_basis_for_restart": ["restart_capacity_allowance"]}
        write(temp / "field_map.json", field_map)
        call(PLANNING, "-B", F01 / "check_f01.py", "--result-a", temp / "A_restart_30.json",
             "--result-b", temp / "B_restart_0.json", "--field-map", temp / "field_map.json",
             "--report", temp / "f01_oracle.json")
        f01["independent_check"] = read(temp / "f01_oracle.json")
        f01["missing_evidence_result"] = solve(split_case("A_restart_30", declared=False))["supply_totals"]
        write(OUT / "f01_correction_evidence.json", f01)

        frozen = temp / "frozen"
        stage = ROOT / "research/implementation/stage5_4a"
        call(IFC, "-B", "-m", "pmi_core.scheduling", "--config", stage / "controlled_schedule_inputs.json",
             "--output", frozen)
        frozen_exports = {f.name: sha256(f.read_bytes()).hexdigest() for f in frozen.iterdir()
                          if f.read_bytes() == (stage / f.name).read_bytes()}
        assert len(frozen_exports) == 8
    t7 = read(REFERENCES / "deliverable_manifest.json")["files"]
    c01 = read(CORRECTION / "correction_manifest.json")
    for entry in t7:
        assert sha256((REFERENCES / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
    for name, digest in c01["files"].items():
        assert sha256((CORRECTION / name).read_bytes()).hexdigest() == digest
    for entry in c01["historical_preserved"].values():
        assert sha256((REFERENCES / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
    for result in after.values():
        if result["validated"]:
            assert len(result["pending_approvals"]) == 88 and all(row["status"] == "PENDING"
                for row in result["pending_approvals"]) and result["real_project_eligible"] is False
    protected = ("research/validation", "research/implementation/stage5_4a",
                 "research/implementation/stage5_3", "research/implementation/stage5_4b/benchmark_exports",
                 "research/implementation/stage5_4b/benchmark_results.json")
    assert not call("git", "diff", "--name-only", "HEAD", "--", *protected).stdout.strip()
    write(OUT / "test_results.json", tests)
    write(OUT / "preservation_verification.json", {"accepted_baseline": BASE,
          "history_and_evidence_unchanged": True, "frozen_exports_sha256": frozen_exports,
          "task7_manifest_files_verified": len(t7), "c01_manifest_files_verified": len(c01["files"]),
          "historical_c01_hashes_verified": len(c01["historical_preserved"]), "pending_approvals": 88,
          "real_project_eligible": False})


if __name__ == "__main__":
    main()
