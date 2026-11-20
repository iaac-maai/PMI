"""Build the final independent acceptance matrix from the evidence produced by verify_final.py.

Mandatory flags come from the Task 7 criteria and the C01 amendment, not from Agent 1's matrix.
Run with: PYTHONHASHSEED=0 .venv-planning/Scripts/python.exe -B .../build_final_matrix.py
"""

import copy
import csv
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "regression"
REPO = HERE.parents[4]
PKG = REPO / "research/validation/stage5_4a_independent_verification"
COR = PKG / "corrections/C01_column_reservation_coverage"
sys.path.insert(0, str(REPO))
from research.implementation.stage5_4b.engine import solve  # noqa: E402
from research.implementation.stage5_4b.fixtures import frozen_r0, normalize_reference, reference_cases  # noqa: E402


def rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def code(r):
    return (r.get("diagnostic") or {}).get("code", "ACCEPT" if r["validated"] else r["status"])


def extra_checks():
    cases = reference_cases()
    out = {}
    base = normalize_reference(cases["RC01"])
    for name, fn, want in [
        ("tick 7", lambda p: p.update(tick_minutes=7), "TICK_MISALIGNED"),
        ("window 08:01", lambda p: p["project_calendar"]["working_windows"][0].update(start="08:01"), "TICK_MISALIGNED"),
        ("scope real project", lambda p: p.update(scope="real_project"), "MODEL_INVALID"),
        ("unknown top-level key", lambda p: p.update(supply_rate=6), "UNSUPPORTED_CONSTRAINT"),
        ("elapsed hold demanding a resource",
         lambda p: p["activities"].append({"id": "H", "kind": "elapsed_hold", "duration_minutes": 60,
                                           "resources": {"CREW_F": 1}, "input_state": "hypothetical_fixture"}),
         "MODEL_INVALID"),
    ]:
        p = copy.deepcopy(base)
        fn(p)
        out[name] = {"result": code(solve(p)), "expected": want}
    p = frozen_r0(5)
    t = next(a for a in p["activities"] if a.get("reference_id") == "S-FORM")
    k = next(iter(t["demand_hours"]))
    t["demand_hours"][k] = t["positive_capacity"][k] * 4
    out["V4 hours exceed units x scheduled time"] = {"result": code(solve(p)), "expected": "MODEL_INVALID"}
    for v in out.values():
        v["pass"] = v["result"] == v["expected"]
    return out


def main():
    ev = json.loads((OUT / "verification_evidence.json").read_text(encoding="utf-8"))
    cases = {r["case_id"]: r["verdict"] == "PASS" for r in rows(OUT / "independent_case_results.csv")}
    bench = {(r["fixture"], r["version"]): r for r in rows(OUT / "independent_benchmark_results.csv")}
    agent = {r["criterion_id"]: r for r in rows(REPO / "research/implementation/stage5_4b/acceptance_matrix.csv")}
    task7 = {r["criterion_id"]: r for r in rows(PKG / "acceptance_criteria.csv")}
    amend = {r["criterion_id"]: r for r in rows(COR / "acceptance_criteria_amendment_v1.1.csv")}
    extra = extra_checks()
    cd, audit, contract = ev["targeted_corrections"], ev["input_state_audit"], ev["contract_diagnostics"]
    pres, frozen, dated = ev["preservation"], ev["frozen_r0"], ev["date_capacity"]

    def b(fixture, version):
        return bench[(fixture, version)]["verdict"] == "PASS"
    all_cases = all(cases.values()) and len(cases) == 30
    v11 = b("original", "v1.1") and b("holiday", "v1.1")
    v10 = b("original", "v1.0") and b("holiday", "v1.0")
    r0 = frozen["5"]["pass"] and frozen["15"]["pass"]
    advanced = all(cases[c] for c in ("RC05a", "RC05b", "RC10a", "RC10c", "RC11a", "RC11b", "RC12a", "RC12b",
                                      "RC12c", "RC12d", "RC12e", "RC13a", "RC13b"))
    dc = all(d["pass"] for d in dated)
    au = all(a["pass"] for a in audit.values())
    ct = all(c["pass"] for c in contract.values())
    ex = all(c["pass"] for c in extra.values())
    preserved = (pres["tests_historical_ok"] and pres["tests_optimizer_ok"] and pres["stage5_4a_exports_identical"] == "8/8"
                 and pres["register_sha256"] == pres["register_expected"] and pres["approvals_pending"] == 88
                 and not pres["task7_manifest_changed"] and not pres["c01_manifest_changed"] and pres["c01_historical_hashes_ok"])

    rules = {
        "AC-G01": (all_cases and v11 and v10, "30/30 statuses; v1.1 OPTIMAL; v1.0 rejected"),
        "AC-G02": (all_cases and v11, "all applicable makespans equal independent optima; benchmarks 40445/41885"),
        "AC-G03": (all_cases and advanced and v11, "independent per-minute timestamp checks on all 30 source cases incl. 13 advanced; 350/350 per benchmark"),
        "AC-G04": (all_cases and v11, "durations, split segment sums and release spans re-derived from source minutes"),
        "AC-G05": (all_cases and v11, "every occupied minute checked against project, resource, exception and allowed-hours calendars"),
        "AC-G06": (all_cases and v11 and dc, "per-minute load incl. continuous reservations and dated capacities"),
        "AC-G07": (all_cases and v11, "FS lags and inspection gates checked from source"),
        "AC-G08": (cases["RC07a"] and cases["RC07b"] and cases["RC07c"], "RC07a-c"),
        "AC-G09": (cases["RC10a"] and cases["RC10c"] and cases["RC10b"] and contract["split without authorization"]["pass"],
                   "segment count/minimum, no voluntary pause, release between segments; unauthorized splits rejected"),
        "AC-G10": (r0 and extra["tick 7"]["pass"] and extra["window 08:01"]["pass"], "R0-5/R0-15 optima; tick and boundary misalignment rejected"),
        "AC-G11": (cases["RC06"] and cases["RC06-D"] and cd["CD05 ignored exception reported"][-1], "RC06 exception, RC06-D default, unauthorized exception ignored and reported"),
        "AC-DEMO-H1": (b("holiday", "v1.1"), "holiday v1.1 OPTIMAL 41885, 350/350 checks"),
        "AC-C-P1": (au and ct, "input-state audit and missing-input rejections"),
        "AC-C-P2": (cases["RC05a"] and cases["RC05b"] and v11, "working-time vs continuous occupancy checked per minute"),
        "AC-C-P3": (r0, "frozen R0 durations equal independent Stage 5.3A-derived durations"),
        "AC-C-P4": (r0 and v11, "costs 1172.5136 and 5103.32664 unchanged; no occupancy cost"),
        "AC-C-P5": (contract["reservation quantity missing"]["pass"], "explicit integer quantity required; no derivation from cost coefficients (code review)"),
        "AC-C-P6": (cd["CD01 explicit-none demanded"][-1] and cd["CD06 R0 explicit-none equipment"][-1], "CD01, CD06"),
        "AC-C-P7": (ct and au, "all invalid inputs rejected before solving; no relaxed schedule"),
        "AC-C-V1": (cases["RC08a"] and contract["reservation on working resource"]["pass"], "undeclared and misclassified resources rejected"),
        "AC-C-V2": (cd["CD01 explicit-none demanded"][-1], "explicit-none demand -> MODEL_INVALID / MISSING_INPUT"),
        "AC-C-V3": (contract["reservation on working resource"]["pass"] and v11, "reusable assets continuous; working resources calendar"),
        "AC-C-V4": (extra["V4 hours exceed units x scheduled time"]["pass"], "inflated mode hours rejected"),
        "AC-C-V5": (r0 and cd["CD02 mode fields without crew_mode"][-1], "C-POUR full HYP-CONC incl. OFICIAL_1; mode fields without mode rejected"),
        "AC-C-V6": (extra["elapsed hold demanding a resource"]["pass"], "elapsed hold with working demand rejected"),
        "AC-C-V7": (contract["V7 release not reachable from start"]["pass"], "unreachable release -> RESERVATION_UNRELEASED"),
        "AC-C-V8": (v11 and v10 and contract["V8 covered activity succeeds release"]["pass"], "108 coverage checks per v1.1; predecessor (v1.0) and successor contradictions rejected"),
        "AC-C-V9": (dc and v11, "dated capacity scenarios equal independent enumeration; benchmarks within capacity"),
        "AC-C-V10": (r0 and v11, "no cost added by occupancy"),
        "AC-C-V11": (extra["tick 7"]["pass"] and extra["window 08:01"]["pass"], "TICK_MISALIGNED; DST/London boundaries"),
        "AC-C-MISSING_INPUT": (cases["RC08a"] and au and contract["supply rate missing"]["pass"], "RC08a, audit, supply"),
        "AC-C-EXPLICIT_NONE_REQUIRED": (cd["CD06 R0 explicit-none equipment"][-1], "R0 declarations; removal rejected"),
        "AC-C-IMPOSSIBLE_CREW": (cases["RC08b"] and cases["RC08c"], "RC08b/c"),
        "AC-C-NO_ELIGIBLE_MODE": (contract["NO_ELIGIBLE_MODE detail"]["pass"], "IMPOSSIBLE_CREW with NO_ELIGIBLE_MODE detail"),
        "AC-C-NO_FIT": (cases["RC08d"] and cases["RC10b"], "RC08d, RC10b"),
        "AC-C-SPLIT_NOT_AUTHORIZED": (contract["split without authorization"]["pass"] and contract["split pour without cold-joint ref"]["pass"], "injections"),
        "AC-C-RESERVATION_UNRELEASED": (contract["V7 release not reachable from start"]["pass"], "injection"),
        "AC-C-RELEASE_CONDITIONAL": (cases["RC12b"] and cases["RC13b"], "RC12b, RC13b conditional projections"),
        "AC-C-TICK_MISALIGNED": (extra["tick 7"]["pass"] and extra["window 08:01"]["pass"], "injections"),
        "AC-C-INFEASIBLE_DEADLINE": (cases["RC07a"], "RC07a"),
        "AC-R2-1": (cases["RC06"] and cases["RC06-D"] and cd["CD05 ignored exception reported"][-1], "RC06, RC06-D, CD05"),
        "AC-R2-2": (r0 and cd["CD02 mode fields without crew_mode"][-1], "R0 reserved OFICIAL_1; CD02"),
        "AC-R2-3": (cases["RC13a"] and cases["RC13b"], "RELEASE finish = max(minimum, recorded); planned test conditional"),
        "AC-R2-4": (all(cases[c] for c in ("RC12a", "RC12b", "RC12c", "RC12d", "RC12e")), "RC12a-e"),
        "AC-D01": (b("original", "v1.1"), "original v1.1 OPTIMAL 40445 = bound, 2027-03-01T10:05"),
        "AC-D02": (v11, "350/350 independent checks per fixture incl. 108 coverage"),
        "AC-D03": (v11, "CPM 16310 min, 29 conflicts, 11 pools"),
        "AC-D04": (v11, "5103.32664 EUR source sum = result cost"),
        "AC-P01": (preserved and cd["CD03 approval/fixture metadata"][-1], "register unchanged; 88 PENDING; injected APPROVED rejected"),
        "AC-P02": (frozen["15"]["pass"] and pres["stage5_4a_exports_identical"] == "8/8", "R0-15 14880; 8/8 exports"),
        "AC-P03": (frozen["5"]["pass"], "R0-5 14850"),
        "AC-P04": (r0, "1172.5136 EUR in both R0 runs"),
        "AC-P05": (extra["scope real project"]["pass"] and r0, "real_project_eligible false everywhere; real scope rejected"),
        "AC-C01-H": (v10, "both v1.0 rejected before solve; named C*-REBAR contradiction; hashes unchanged"),
        "AC-C01-M": (v11 and all(bench[(f, 'v1.1')]["manifest_sha256_match"] == "True" and bench[(f, 'v1.1')]["coverage_sensitivity"] == "False"
                                 for f in ("original", "holiday")), "manifest hashes; coverage sensitivity off"),
    }
    out = []
    for cid, a in agent.items():
        src = amend.get(cid) or task7.get(cid)
        mandatory = (src or {}).get("mandatory_for_controlled_cpsat", "")
        revision = "C01 new" if cid in amend and amend[cid]["amendment"] == "new" else \
            "C01 amended" if cid in amend else "Task 7"
        if cid == "AC-D05":
            disp, evid = "NOT_APPLICABLE", "alternative optima; dates not compared (agreed)"
        elif cid in rules:
            ok, evid = rules[cid]
            disp = "ACCEPTED" if ok else "NOT_ACCEPTED"
        else:
            case_id = cid[3:]
            ok = cases.get(case_id, False)
            disp, evid = ("ACCEPTED" if ok else "NOT_ACCEPTED"), f"independent_case_results.csv {case_id}"
        out.append({"criterion_id": cid, "mandatory": mandatory, "mandatory_agent1": a["mandatory"],
                    "mandatory_consistent": mandatory == a["mandatory"], "revision": revision,
                    "agent1_status": a["status"], "independent_disposition": disp, "independent_evidence": evid})
    with (OUT / "final_acceptance_matrix.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, list(out[0]))
        w.writeheader()
        w.writerows(out)
    mand = [r for r in out if r["mandatory"] == "yes"]
    summary = {"criteria": len(out), "mandatory": len(mand),
               "mandatory_accepted": sum(r["independent_disposition"] == "ACCEPTED" for r in mand),
               "mandatory_flags_consistent": all(r["mandatory_consistent"] for r in out),
               "not_accepted": [r["criterion_id"] for r in out if r["independent_disposition"] == "NOT_ACCEPTED"],
               "extra_checks": extra}
    (OUT / "matrix_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
