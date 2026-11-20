"""Independent end-to-end verification of pmi_core.application (registered R0 configuration, 5 and 15 min).

Run with the planning interpreter from the repo root. The IFC itself is read independently with IfcOpenShell in
the IFC interpreter; schedules are re-checked with the independent Stage 5.4A model (verify_core.check_r0).
"""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
REPO = HERE.parents[4]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "research/validation/stage5_4b_independent/core/scripts"))
sys.path.insert(0, str(REPO / "research/validation/stage5_4a_independent_verification/scripts"))
import verify_core as core  # noqa: E402  independent R0 checker
import independent_cpm as ind  # noqa: E402

PLAN = REPO / ".venv-planning/Scripts/python.exe"
IFCPY = REPO / ".venv/Scripts/python.exe"
CONFIG = REPO / "research/implementation/stage5_4b_integration/r0_config.json"
IFC = REPO / "research/implementation/stage5_2/controlled_frame.ifc"
COMMITTED_HANDOVER = REPO / "research/implementation/stage5_3/scheduling_handover.json"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def ifc_elements():
    code = ("import ifcopenshell,json,sys;f=ifcopenshell.open(sys.argv[1]);"
            "print(json.dumps(sorted([e.GlobalId,e.is_a()] for t in ('IfcColumn','IfcBeam','IfcSlab') for e in f.by_type(t))))")
    return json.loads(subprocess.run([str(IFCPY), "-B", "-c", code, str(IFC)], capture_output=True, text=True, check=True).stdout)


def run_pipeline(tick, out):
    proc = subprocess.run([str(PLAN), "-B", "-m", "pmi_core.application", "--config", str(CONFIG), "--output", str(out),
                           "--ifc-python", str(IFCPY), "--planning-python", str(PLAN), "--tick", str(tick)],
                          cwd=REPO, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def as_check_r0_result(schedule):
    """Shape the unified output for the independent R0 checker (reference_id, resources, segments)."""
    acts = []
    for a in schedule["activities"]:
        o = a["optimized"]
        acts.append({"reference_id": a["reference_id"], "start": o["start"], "finish": o["finish"],
                     "segments": o["segments"], "resources": a["resources_demand"]})
    return {"activities": acts, "objective_minutes": schedule["proof"]["project_makespan_minutes"]}


def main():
    ifc_truth = ifc_elements()
    truth_ids = {g for g, _ in ifc_truth}
    out, tmp = {}, Path(tempfile.mkdtemp(prefix="pmi_e2e_"))
    try:
        for tick, target in ((5, 14850), (15, 14880)):
            run_dir = tmp / f"r0_{tick}"
            code, stdout, stderr = run_pipeline(tick, run_dir)
            sched = json.loads((run_dir / "schedule.json").read_text(encoding="utf-8"))
            evidence = json.loads((run_dir / "pipeline_evidence.json").read_text(encoding="utf-8"))
            handover_path = run_dir / "estimation/scheduling_handover.json"
            handover = json.loads(handover_path.read_text(encoding="utf-8"))
            bim = json.loads((run_dir / "construction/import.json").read_text(encoding="utf-8"))
            acts = sched["activities"]
            # resources per activity come from the optimized result ledger (working_time rows)
            demand = {}
            for row in sched["resource_occupancy"]:
                if row["occupancy_basis"] == "working_time":
                    demand.setdefault(row["holder_id"], {})[row["resource_id"]] = row["demand"]
            for a in acts:
                a["resources_demand"] = demand.get(a["activity_id"], {})
            errs, info = core.check_r0(tick, as_check_r0_result(sched))
            gids = {a["ifc_global_id"] for a in acts}
            per_element = {g: sum(1 for a in acts if a["ifc_global_id"] == g) for g in gids}
            handover_ids = {a["id"] for a in handover["activities"]}
            stage_ok = all(sha({"canonical_bim": run_dir / "construction/import.json",
                                "construction": run_dir / "construction/construction.json",
                                "estimation": handover_path}[k]) == v for k, v in evidence["stage_payload_sha256"].items())
            optimized_has_critical = any("critical" in json.dumps(a["optimized"]) for a in acts)
            baseline_vs_opt = sum(1 for a in acts if a["baseline"]["start"] != a["optimized"]["start"])
            res = {
                "exit_code": code, "stdout": json.loads(stdout) if stdout.strip().startswith("{") else stdout[-300:],
                "source_ifc_sha256": sched["source_ifc_sha256"], "ifc_file_sha256": sha(IFC),
                "evidence_input_ifc_sha256": evidence["input_sha256"]["ifc"],
                "model_version_id": sched["model_version_id"], "handover_model_version_id": handover["model_version_id"],
                "bim_model_version_id": bim.get("model_version_id") or bim.get("model", {}).get("id"),
                "runtimes": {k: {"python": v["python"], "dependency": v["dependency"], "version": v["version"],
                                 "executable": Path(v["executable"]).as_posix().split("/PMI/PMI/")[-1]}
                             for k, v in evidence["runtimes"].items()},
                "stage_payload_hashes_match_files": stage_ok,
                "pipeline_handover_equals_committed_stage5_3": sha(handover_path) == sha(COMMITTED_HANDOVER),
                "ifc_elements_independent": ifc_truth, "activity_global_ids_subset_of_ifc": gids <= truth_ids,
                "all_ifc_elements_scheduled": gids == truth_ids, "activities_per_element": per_element,
                "activities": len(acts), "activity_ids_equal_pipeline_handover": {a["activity_id"] for a in acts} == handover_ids,
                "work_packages": len(sched["work_packages"]),
                "package_ids": sorted(p["id"] for p in sched["work_packages"]),
                "activity_package_ids_in_packages": {a["work_package_id"] for a in acts} <= {p["id"] for p in sched["work_packages"]},
                "dependencies": len(sched["dependencies"]),
                "dependency_endpoints_mapped": all(d.get("predecessor_id", d.get("predecessor")) in {a["activity_id"] for a in acts}
                                                   and d.get("successor_id", d.get("successor")) in {a["activity_id"] for a in acts}
                                                   for d in sched["dependencies"]),
                "proof": sched["proof"], "target": target,
                "independent_check_errors": errs, "independent_cpm_makespan": info and info.get("independent_cpm_makespan"),
                "cpm_makespan": sched["cpm"]["makespan_minutes"], "cpm_critical_ids": len(sched["cpm"]["critical_activity_ids"]),
                "critical_only_in_baseline": not optimized_has_critical and all("cpm_critical" in a["baseline"] for a in acts),
                "activities_where_optimized_start_differs_from_cpm": baseline_vs_opt,
                "cost": sched["cost"], "pending_approvals": len(sched["pending_approvals"]),
                "pending_all": all(r["status"] == "PENDING" for r in sched["pending_approvals"]),
                "fixture_exceptions": [e["id"] for e in sched["fixture_exceptions"]],
                "real_project_eligible": sched["real_project_eligible"],
                "internal_timestamp_validated": sched["internal_timestamp_validated"],
                "_ids_for_stability": {"packages": sorted(p["id"] for p in sched["work_packages"]),
                                       "activities": sorted(a["activity_id"] for a in acts)},
            }
            res["pass"] = (code == 0 and res["source_ifc_sha256"] == res["ifc_file_sha256"] == res["evidence_input_ifc_sha256"]
                           == "8932ed0e043a1fb1252e51b223166c5c15b81f4969018a7e18c49e2802282c2c"
                           and res["model_version_id"] == res["handover_model_version_id"] and stage_ok
                           and res["all_ifc_elements_scheduled"] and set(per_element.values()) == {7}
                           and res["activities"] == 21 and res["activity_ids_equal_pipeline_handover"]
                           and res["work_packages"] == 3 and res["activity_package_ids_in_packages"]
                           and res["dependencies"] == 28 and res["dependency_endpoints_mapped"]
                           and sched["proof"]["schedule_scope"] == "complete_project"
                           and sched["proof"]["project_makespan_minutes"] == sched["proof"]["lower_bound_minutes"] == target
                           and sched["proof"]["solver_status"] == "OPTIMAL" and not errs
                           and res["critical_only_in_baseline"] and abs(sched["cost"]["total_direct_reference_eur"] - 1172.5136) < 1e-9
                           and res["pending_approvals"] == 88 and res["pending_all"]
                           and res["fixture_exceptions"] == [f"FX-R0-0{i}" for i in range(1, 7)]
                           and res["real_project_eligible"] is False and res["internal_timestamp_validated"]
                           and res["runtimes"]["ifc"]["dependency"] == "ifcopenshell"
                           and res["runtimes"]["planning"]["dependency"] == "ortools")
            out[f"tick_{tick}"] = res
        # Stable identities across resolutions
        stable = out["tick_5"]["_ids_for_stability"] == out["tick_15"]["_ids_for_stability"]
        # Derivation: the worker consumes the pipeline handover. A tampered copy must be rejected.
        tampered_dir = tmp / "tamper"
        tampered_dir.mkdir()
        src = tmp / "r0_5" / "estimation/scheduling_handover.json"
        hand = json.loads(src.read_text(encoding="utf-8"))
        first = next(a for a in hand["activities"] if a["kind"] == "productive")
        first["productive_hours"] = first["productive_hours"] * 2
        t_path = tampered_dir / "scheduling_handover.json"
        t_path.write_text(json.dumps(hand), encoding="utf-8")
        proc = subprocess.run([str(PLAN), "-B", "-m", "research.implementation.stage5_4b_integration.r0_worker",
                               "--handover", str(t_path), "--evidence", str(tmp / "r0_5/pipeline_evidence.json"),
                               "--output", str(tampered_dir / "out.json"), "--project-id", "PMI-CONTROLLED", "--tick", "5"],
                              cwd=REPO, capture_output=True, text=True)
        tamper = {"modified": f"{first['id']} productive_hours x2", "exit_code": proc.returncode,
                  "rejected": proc.returncode != 0 and not (tampered_dir / "out.json").exists(),
                  "message_tail": (proc.stderr or proc.stdout)[-240:]}
        # Hash gate: a different IFC is refused before any stage runs.
        bad_cfg = tmp / "cfg.json"
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        cfg["ifc_sha256"] = "0" * 64
        bad_cfg.write_text(json.dumps(cfg), encoding="utf-8")
        proc = subprocess.run([str(PLAN), "-B", "-m", "pmi_core.application", "--config", str(bad_cfg),
                               "--output", str(tmp / "badrun"), "--ifc-python", str(IFCPY), "--planning-python", str(PLAN)],
                              cwd=REPO, capture_output=True, text=True)
        hash_gate = {"exit_code": proc.returncode, "rejected": proc.returncode != 0 and not (tmp / "badrun").exists(),
                     "message": (proc.stderr or proc.stdout).strip()[-160:]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for k in ("tick_5", "tick_15"):
        out[k].pop("_ids_for_stability")
    result = {"pipeline": "pmi_core.application --config research/implementation/stage5_4b_integration/r0_config.json",
              "runs": out, "identities_stable_across_ticks": stable, "derivation_tamper_test": tamper,
              "ifc_hash_gate": hash_gate,
              "pass": out["tick_5"]["pass"] and out["tick_15"]["pass"] and stable and tamper["rejected"] and hash_gate["rejected"]}
    (OUT / "end_to_end_verification.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("identities_stable_across_ticks", "derivation_tamper_test", "ifc_hash_gate", "pass")}, indent=1))
    for k, v in out.items():
        print(k, v["pass"], v["proof"]["project_makespan_minutes"], v["proof"]["lower_bound_minutes"], v["cost"],
              v["activities_per_element"], v["dependencies"], v["work_packages"], v["independent_check_errors"][:3],
              v["pipeline_handover_equals_committed_stage5_3"], v["activities_where_optimized_start_differs_from_cpm"], v["runtimes"])


if __name__ == "__main__":
    main()
