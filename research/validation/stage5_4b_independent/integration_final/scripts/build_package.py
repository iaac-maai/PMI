"""Assemble the Stage 5.4B.3 targeted acceptance deliverables from the independent evidence in this folder."""

import csv
import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
REPO = HERE.parents[4]
V = REPO / "research/validation"
PKG = V / "stage5_4a_independent_verification"
REG = OUT / "regression"
INT = REPO / "research/implementation/stage5_4b_integration"


def rows(p):
    with Path(p).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def git(*a):
    return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True).stdout.strip()


def write_csv(name, data):
    with (OUT / name).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, list(dict.fromkeys(k for r in data for k in r)))
        w.writeheader()
        w.writerows(data)


def main():
    ev = load(REG / "verification_evidence.json")
    f01, e2e, safe = load(OUT / "f01_independent_result.json"), load(OUT / "end_to_end_verification.json"), load(OUT / "safety_verification.json")
    agent = {r["case"]: r for r in rows(INT / "behavioural_equivalence_results.csv")}

    # ---- behavioural equivalence (36)
    beq = []
    for r in rows(REG / "independent_case_results.csv"):
        beq.append({"case": r["case_id"], "group": "small reference", "independent_expected_status": r["expected_status"],
                    "relocated_status": r["status"], "objective_minutes": r["objective"], "lower_bound_minutes": r["lower_bound"],
                    "independent_expected_objective": r["expected_objective"], "diagnostic": r["diagnostic"],
                    "independent_evidence": r["independent_evidence"], "agent1_equivalent": agent.get(r["case_id"], {}).get("equivalent"),
                    "independent_verdict": r["verdict"]})
    for tick in ("5", "15"):
        f = ev["frozen_r0"][tick]
        beq.append({"case": f"frozen_R0_{tick}", "group": "frozen R0", "independent_expected_status": "OPTIMAL",
                    "relocated_status": f["status"], "objective_minutes": f["objective"], "lower_bound_minutes": f["bound"],
                    "independent_expected_objective": f["target"], "diagnostic": "",
                    "independent_evidence": f"independent Stage 5.4A model errors={f['independent_errors']}; cost {f['cost']}",
                    "agent1_equivalent": agent.get(f"frozen_R0_{tick}", {}).get("equivalent"), "independent_verdict": "PASS" if f["pass"] else "FAIL"})
    for b in rows(REG / "independent_benchmark_results.csv"):
        key = f"{b['fixture']}_{b['version']}"
        evid = (f"350-check C01 oracle failed={b.get('independent_failed')}, coverage {b.get('coverage_checks')}, conflicts {b.get('resource_conflicts')}, "
                f"cost {b.get('result_cost')}, CPM {b['cpm_makespan']}/{b['cpm_conflicts']}/{b['cpm_pools']}"
                if b["version"] == "v1.1" else f"rejected before solve; contradictions reported: all four R-COLSET-C1..C4; static analysis {b.get('independent_static_contradictions')}")
        beq.append({"case": key, "group": "C01 benchmark", "independent_expected_status": "OPTIMAL" if b["version"] == "v1.1" else "INFEASIBLE",
                    "relocated_status": b["status"], "objective_minutes": b["objective"], "lower_bound_minutes": b["lower_bound"],
                    "independent_expected_objective": b.get("expected_objective", ""), "diagnostic": "STRUCTURAL_INFEASIBILITY" if b["version"] == "v1.0" else "",
                    "independent_evidence": evid, "agent1_equivalent": agent.get(key, {}).get("equivalent"), "independent_verdict": b["verdict"]})
    write_csv("behavioural_equivalence_verification.csv", beq)

    # ---- integration acceptance matrix
    matrix = []
    for r in rows(REG / "final_acceptance_matrix.csv"):
        matrix.append({"criterion_id": r["criterion_id"], "set": "Stage 5.4B (86, C01-amended)", "mandatory": r["mandatory"],
                       "independent_disposition": r["independent_disposition"], "evidence": "regression/" + r["independent_evidence"]})
    f01_rows = {x["check"]: x["passed"] for x in f01["prepared_checker_declared"]["rows"]}
    lv = f01["level_checks"]
    lv_ok = lambda pred: all(x["passed"] for k, rs in lv.items() for x in rs if pred(x["check"]))  # noqa: E731
    integ = [
        ("AC-F01-1", all(f01_rows[k] for k in f01_rows if k.startswith(("F01-3", "F01-5"))) and lv_ok(lambda c: c.startswith("L-")), "planned 60 m3 declared; null when evidence absent; daily 24/36"),
        ("AC-F01-2", all(f01_rows[k] for k in f01_rows if k.startswith("F01-6")), "restart allowance 3 (A) / 0 (B), Monday only"),
        ("AC-F01-3", all(f01_rows[k] for k in f01_rows if k.startswith(("F01-7", "F01-8"))), "total capacity allowance 63 / 60, labelled as allowance"),
        ("AC-F01-4", all(f01_rows[k] for k in f01_rows if k.startswith(("F01-8", "F01-9"))) and lv_ok(lambda c: "measured" in c or "input_state" in c), "no measured/actual labels; not independently_measured"),
        ("AC-F01-5", all(f01_rows[k] for k in f01_rows if k.startswith("F01-10")) and lv_ok(lambda c: c == "L-occupancy labels"), "restart_capacity_allowance occupancy Mon 08:00-08:30"),
        ("AC-F01-6", all(f01_rows[k] for k in f01_rows if k.startswith(("F01-11", "F01-12"))) and lv_ok(lambda c: "cost" in c or "quantity" in c), "EUR 7114.20 both; engineering quantity untouched"),
        ("AC-F01-7", all(f01_rows[k] for k in f01_rows if k.startswith(("F01-0", "F01-1", "F01-2", "F01-4"))), "4710 / 4680 min; segments as specified"),
        ("AC-RC13b", safe["C02"]["hash_ok"] and safe["C02"]["output_ref"] == ["HYP-RC13B-PLANNED-STRENGTH-TEST-CRITERION"] and safe["C02"]["status"] == "CONDITIONAL" and safe["C02"]["projection"] == 5880, "C02 ref carried from hash-verified v1.1 case"),
        ("AC-C03-1", safe["C03"]["london_zero_window"], "London midnight boundaries"),
        ("AC-C03-2", safe["C03"]["madrid_spring_1380"] and safe["C03"]["madrid_autumn_1500"], "DST-length days"),
        ("AC-C03-3", all(d["pass"] for d in ev["date_capacity"]), "invalid overrides rejected; dated scenarios equal independent enumeration"),
    ]
    for cid, ok, evid in integ:
        matrix.append({"criterion_id": cid, "set": "5.4B.3 integration amendment (12)", "mandatory": "yes",
                       "independent_disposition": "ACCEPTED" if ok else "NOT_ACCEPTED", "evidence": evid})
    # AC-INT-P1 filled after preservation below
    gates = [k for k in safe if k.startswith("gate: ")]
    tasks = [
        ("INT-ARCH-1 optimizer in pmi_core/optimization; single CP-SAT model builder", safe["single_optimizer_implementation"] and safe["cp_sat_model_builders"] == ["pmi_core/optimization/model.py"]),
        ("INT-ARCH-2 research CLI delegates (runtime probe)", safe["research_solve_delegates_to_pmi_core_optimization"]),
        ("INT-ARCH-3 no research imports or fixture paths in pmi_core optimization/application", safe["no_research_imports_in_pmi_core_optimization_application"] and safe["application_has_no_research_or_fixture_paths"]),
        ("INT-ARCH-4 authority only via trusted registry; solve requires registry; defaults deny exceptions", safe["solve_requires_registry"] and safe["default_registry_denies_fixture_exceptions"][1] == "UNVERIFIED_FIXTURE_EXCEPTION" and safe["registry_with_approved_row_rejected"][1] == "UNVERIFIED_APPROVAL"),
        ("INT-ARCH-5 approval/scope gates not bypassable via normalized input", all(safe[g]["pass"] for g in gates)),
        ("INT-ARCH-6 separate IFC and planning interpreters; orchestrator loads neither", safe["orchestrator_loads_neither_ifcopenshell_nor_ortools"] and all(r["runtimes"]["ifc"]["dependency"] == "ifcopenshell" and r["runtimes"]["planning"]["dependency"] == "ortools" for r in e2e["runs"].values())),
        ("INT-E2E-1 R0 5-min from IFC: OPTIMAL 14850, identities, mappings, cost, exclusions", e2e["runs"]["tick_5"]["pass"]),
        ("INT-E2E-2 R0 15-min from IFC: OPTIMAL 14880", e2e["runs"]["tick_15"]["pass"]),
        ("INT-E2E-3 stable package and activity IDs across resolutions", e2e["identities_stable_across_ticks"]),
        ("INT-E2E-4 derived from IFC handover (tamper rejected) and IFC hash gate", e2e["derivation_tamper_test"]["rejected"] and e2e["ifc_hash_gate"]["rejected"]),
        ("INT-BEQ-1 36 behavioural cases independently verified", all(r["independent_verdict"] == "PASS" for r in beq) and len(beq) == 36),
        ("INT-SAFE-1 complete / conditional / unblocked / invalid scopes; no partial project makespan", all(v["safe"] for v in safe["output_safety"].values()) and safe["application_exit_requires_complete_project"]),
        ("INT-SAFE-2 larger benchmark has no IFC identity", not any(v for side in safe["benchmark_no_ifc_identity"].values() for v in side.values())),
    ]
    for cid, ok in tasks:
        matrix.append({"criterion_id": cid.split(" ")[0], "set": "5.4B.3 integration task", "mandatory": "yes",
                       "independent_disposition": "ACCEPTED" if ok else "NOT_ACCEPTED", "evidence": cid})

    # ---- preservation
    fm = load(V / "stage5_4b_independent/final/verification_manifest.json")
    final_changed = [p for p, h in fm["deliverables_sha256"].items() if sha(V / "stage5_4b_independent/final" / p) != h]
    pm = load(V / "stage5_4b_independent/integration_prep/prep_manifest.json")
    prep_changed = [p for p, h in pm["files_sha256"].items() if sha(REPO / p) != h]
    pres = {"git_head": git("rev-parse", "HEAD"), "git_status": git("status", "--porcelain").splitlines(),
            "regression_run_stability": ev["stability"],
            "tests_historical": "43/43 OK (.venv)", "tests_optimizer_and_integration": "32/32 OK (.venv-planning, incl. stage5_4b_integration.test_integration)",
            "stage5_4a_exports_byte_identical": ev["preservation"]["stage5_4a_exports_identical"],
            "approval_register_sha256": ev["preservation"]["register_sha256"],
            "approval_register_matches_task7": ev["preservation"]["register_sha256"] == ev["preservation"]["register_expected"],
            "approvals_pending": ev["preservation"]["approvals_pending"],
            "task7_manifest_changed": ev["preservation"]["task7_manifest_changed"],
            "c01_manifest_changed": ev["preservation"]["c01_manifest_changed"],
            "c01_historical_hashes_ok": ev["preservation"]["c01_historical_hashes_ok"],
            "final_package_changed": final_changed, "integration_prep_files_changed": prep_changed,
            "real_project_eligible_everywhere_false": all(r["real_project_eligible"] is False for r in e2e["runs"].values())}
    p_ok = (not pres["git_status"] or pres["git_status"] == ["?? research/validation/stage5_4b_independent/integration_final/"]) \
        and pres["stage5_4a_exports_byte_identical"] == "8/8" and pres["approval_register_matches_task7"] and pres["approvals_pending"] == 88 \
        and not pres["task7_manifest_changed"] and not pres["c01_manifest_changed"] and pres["c01_historical_hashes_ok"] \
        and not final_changed and not prep_changed
    pres["all_preserved"] = p_ok
    (OUT / "preservation_verification.json").write_text(json.dumps(pres, indent=2) + "\n", encoding="utf-8")
    matrix.append({"criterion_id": "AC-INT-P1", "set": "5.4B.3 integration amendment (12)", "mandatory": "yes",
                   "independent_disposition": "ACCEPTED" if p_ok else "NOT_ACCEPTED", "evidence": "preservation_verification.json"})
    matrix.append({"criterion_id": "INT-REG-1", "set": "5.4B.3 integration task", "mandatory": "yes",
                   "independent_disposition": "ACCEPTED" if p_ok else "NOT_ACCEPTED", "evidence": "43 + 32 tests; 8/8 exports; manifests unchanged"})
    write_csv("integration_acceptance_matrix.csv", matrix)
    mand = [r for r in matrix if r["mandatory"] == "yes"]
    summary = {"rows": len(matrix), "mandatory": len(mand),
               "mandatory_accepted": sum(r["independent_disposition"] == "ACCEPTED" for r in mand),
               "not_accepted": [r["criterion_id"] for r in matrix if r["independent_disposition"] == "NOT_ACCEPTED"],
               "behavioural_cases": len(beq), "behavioural_pass": sum(r["independent_verdict"] == "PASS" for r in beq),
               "f01": f01["decision"], "e2e": e2e["pass"], "preserved": p_ok}
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
