"""Stage 5.4B.3 regression re-run of the accepted Stage 5.4B.2 independent oracle (adapted copy of final/scripts/verify_final.py:
OUT -> integration_final/regression; supply fields pmi-optimization-result/2; v1.0 must list all four contradictions).
Original docstring follows. Final independent Stage 5.4B.2 verification. Run from the repo root with .venv-planning:

    PYTHONHASHSEED=0 .venv-planning/Scripts/python.exe -B research/validation/stage5_4b_independent/final/scripts/verify_final.py

System under test: research.implementation.stage5_4b (solve, adapters, CLI). Oracles:
  * expected outcomes: the Task 4 exhaustive engine re-run under the R2 default calendar policy (with dated
    capacities applied independently where a scenario declares them) and the Task 7 / C01 reference values;
  * a per-minute checker that reads the ORIGINAL reference-case JSON (never Agent 1's normalized problem);
  * the C01 coverage-aware checker on the v1.1 benchmark source JSON;
  * the independent Stage 5.4A model for frozen R0.
"""

import copy
import csv
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from fractions import Fraction
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

assert os.environ.get("PYTHONHASHSEED") == "0", "run with PYTHONHASHSEED=0"
HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "regression"
REPO = HERE.parents[4]
PKG = REPO / "research/validation/stage5_4a_independent_verification"
COR = PKG / "corrections/C01_column_reservation_coverage"
IMPL = REPO / "research/implementation/stage5_4b"
for p in (REPO, PKG / "scripts", COR / "scripts", REPO / "research/validation/stage5_4b_independent/core/scripts"):
    sys.path.insert(0, str(p))

from research.implementation.stage5_4b.engine import solve, validate  # noqa: E402  (system under test)
from research.implementation.stage5_4b.fixtures import frozen_r0, normalize_reference, reference_cases, approvals  # noqa: E402
from research.implementation.stage5_4b.capacity_dates import capacity_periods  # noqa: E402
import build_task7_cases as t7  # noqa: E402  (Task 4 engine + R2 default policy)
import correct_and_verify as c01  # noqa: E402  (C01 coverage-aware checker; own code)
import verify_core as core  # noqa: E402  (independent R0 checker)

t4 = t7.t4
PY = sys.executable


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def epoch(text):
    return int(datetime.fromisoformat(text).timestamp() // 60)


def local_epoch(text, zone):
    return int(datetime.fromisoformat(text).replace(tzinfo=zone).timestamp() // 60)


def git(*a):
    return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True).stdout


def impl_hashes():
    return {p.relative_to(REPO).as_posix(): sha(p) for p in sorted(IMPL.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}


# --------------------------------------------------------------------------- independent small-case checker
def is_open(cal, project, minute, zone):
    return core.is_open(cal, project, minute, zone)


def cap_at(case, rid, minute, zone):
    spec = case["resources"][rid]
    by_date = spec.get("capacity_by_date") or {}
    if by_date:
        cal = spec.get("calendar")
        tz = ZoneInfo(cal["timezone"]) if isinstance(cal, dict) and "timezone" in cal else zone
        day = datetime.fromtimestamp(minute * 60, tz).date().isoformat()
        if day in by_date:
            return by_date[day]
    return spec["capacity"]


def check_small(case, result, exception=None):
    """Return a list of violations of the returned timestamps against the source case."""
    zone = ZoneInfo(case["timezone"])
    tick = case["tick_minutes"]
    origin = local_epoch(case["project_start"], zone)
    acts = {a["id"]: a for a in case["activities"]}
    rows = {r["id"]: r for r in result["activities"]}
    blocked = set((result.get("blocked_activities") or {}).keys())
    err = []
    want = set(acts) - blocked
    if set(rows) != want:
        return [f"activity set {sorted(set(rows) ^ want)}"]
    seg = {k: [(epoch(a), epoch(b)) for a, b in r["segments"]] for k, r in rows.items()}
    span = {k: (epoch(r["start"]), epoch(r["finish"])) for k, r in rows.items()}
    strength = {e["release_activity"]: e for e in case.get("strength_events", [])}
    pour_of = {}
    for k in strength:
        pour_of[k] = next(d["predecessor"] for d in case["dependencies"] if d["successor"] == k)
    for k, r in rows.items():
        a = acts[k]
        s, f = span[k]
        if (s, f) != (seg[k][0][0], seg[k][-1][1]):
            err.append(f"{k}: span/segments mismatch")
        dur = math.ceil(round(a["duration_minutes"] / tick, 9)) * tick
        if k in strength:
            ev = strength[k]
            p_end = span[pour_of[k]][1]
            minimum = dur
            if ev["status"] in ("planned", "pending_result"):
                minimum = max(minimum, ev["test_age_hours_after_pour"] * 60)
            target = p_end + minimum
            if ev["status"] in ("recorded_pass", "hypothetical_recorded_pass"):
                target = max(target, local_epoch(ev["at"], zone))
            if (s, f) != (p_end, target):
                err.append(f"{k}: release {s}-{f} != pour finish..{target}")
            continue
        split = a.get("split") if a.get("interruption") == "split_allowed" else None
        work = sum(b - x for x, b in seg[k])
        if split:
            if len(seg[k]) > split["max_segments"] or work != dur or \
                    any(b - x < split["min_segment_minutes"] for x, b in seg[k]):
                err.append(f"{k}: split rules")
            for (x0, b0), (x1, b1) in zip(seg[k], seg[k][1:]):  # no voluntary pause: no open minute skipped
                cals = [case["project_calendar"]] + [case["resources"][r].get("calendar", "project") for r in a["resources"]]
                if any(all(is_open(c, case["project_calendar"], m, zone) for c in cals) for m in range(b0, x1)):
                    err.append(f"{k}: voluntary pause between segments")
        elif len(seg[k]) != 1 or f - s != dur:
            err.append(f"{k}: duration {f - s} != {dur}")
        if (s - origin) % tick:
            err.append(f"{k}: off grid")
        if a.get("not_before") and s < local_epoch(a["not_before"], zone):
            err.append(f"{k}: before not_before")
        if a["kind"] == "elapsed_hold":
            continue
        cals = [case["project_calendar"] if not (exception and k in exception["activities"])
                else case["resources"][exception["resource"]]["calendar"]]
        cals += [case["resources"][r].get("calendar", "project") for r in a.get("resources", {})]
        for x, b in seg[k]:
            for m in range(x, b):
                if not all(is_open(c, case["project_calendar"], m, zone) for c in cals):
                    err.append(f"{k}: closed calendar")
                    break
                if a.get("allowed_hours"):
                    hm = datetime.fromtimestamp(m * 60, zone).strftime("%H:%M")
                    if not any(lo <= hm < hi for lo, hi in a["allowed_hours"]):
                        err.append(f"{k}: outside allowed_hours")
                        break
    deps = [(d["predecessor"], d["successor"], d["lag_minutes"]) for d in case["dependencies"]]
    for ev in case.get("inspection_pass_events", []):
        for g in ev["gates"]:
            deps.append((ev["inspection_activity"], g, 0))
            if ev["status"] == "recorded_pass" and g in span:
                if span[g][0] < local_epoch(ev["at"], zone) or span[ev["inspection_activity"]][1] > local_epoch(ev["at"], zone):
                    err.append(f"recorded pass gate {g}")
    for x, y, lag in deps:
        if x in span and y in span and span[y][0] < span[x][1] + math.ceil(round(lag / tick, 9)) * tick:
            err.append(f"precedence {x}->{y}")
    load = defaultdict(lambda: defaultdict(int))
    for k, a in acts.items():
        if k not in seg or k in strength:
            continue
        for r, q in a.get("resources", {}).items():
            for x, b in seg[k]:
                for m in range(x, b):
                    load[r][m] += q
    for rv in case.get("reservations", []):
        lo, hi = span[rv["from_activity"]][0], span[rv["to_activity"]][1]
        for m in range(lo, hi):
            load[rv["resource"]][m] += rv["demand"]
    for r, per in load.items():
        bad = [m for m, v in per.items() if v > cap_at(case, r, m, zone)]
        if bad:
            err.append(f"capacity {r} at {datetime.fromtimestamp(min(bad) * 60, zone):%Y-%m-%d %H:%M}")
    finish = max(f for _, f in span.values())
    for d in case.get("deadlines", []):
        lim = local_epoch(d["latest_finish"], zone)
        if (finish if d["activity"] == "PROJECT" else span[d["activity"]][1]) > lim:
            err.append(f"deadline {d['activity']}")
    if result.get("objective_minutes") != finish - origin:
        err.append(f"objective {result.get('objective_minutes')} != {finish - origin}")
    return err


def t4_expected(case, policy_exception=False):
    c = {k: v for k, v in case.items() if k != "expected"}
    if policy_exception:
        c["calendar_policy"] = t7.EXCEPTION_POLICY
    if c["case_id"].startswith("R0-"):
        return t4.solve_fixture(c)
    return t4.solve_case(c)


_prepare_policy = t4.prepare


def prepare_dated(case):
    """Task 4 model with dated capacities applied independently of Agent 1's capacity_periods()."""
    model = _prepare_policy(case)
    zone = model["zone"]
    for r, spec in case["resources"].items():
        by_date = spec.get("capacity_by_date") or {}
        if not by_date:
            continue
        cal = spec.get("calendar")
        tz = ZoneInfo(cal["timezone"]) if isinstance(cal, dict) and "timezone" in cal else zone
        for i in range(model["n"]):
            day = datetime.fromtimestamp((model["anchor"] + i * model["tick"]) * 60, tz).date().isoformat()
            if day in by_date and (model["cap"][r][i] or cal == "continuous"):
                model["cap"][r][i] = by_date[day]
    return model


# --------------------------------------------------------------------------- main
def main():
    started = {"head": git("rev-parse", "HEAD").strip(), "status": git("status", "--porcelain").splitlines(),
               "impl": impl_hashes()}
    cases = reference_cases()
    t7cases = {c["case_id"]: c for c in json.loads((PKG / "task7_reference_cases.json").read_text(encoding="utf-8"))["cases"]}
    case_rows = []

    # ---- 2. AC-G03: all 30 small cases
    for cid, case in sorted(cases.items()):
        if cid == "DEMO-H1":
            continue
        res = solve(normalize_reference(case))
        if cid in t7cases and cid != "RC06":
            exp = t7cases[cid]["expected"]
            exp_status = exp["expected_status"]
            exp_obj = exp.get("optimal_makespan_minutes")
            exp_sched = {r["id"]: (r["start"], r["finish"]) for r in exp.get("schedule", []) if r["id"] != "RELEASE"}
            exp_code = exp.get("preflight_code", "")
            unique = True
        else:
            exp = t4_expected(case, policy_exception=(cid == "RC06"))
            exp_status, exp_obj = exp["expected_status"], exp.get("optimal_makespan_minutes")
            exp_code = exp.get("preflight_code", "")
            unique = exp.get("unique_optimal_schedule") is True
            exp_sched = {r["id"]: (r["start"], r["finish"]) for r in exp.get("reference_schedule", [])} if unique else {}
        notes, ok = [], res["status"] == exp_status
        if exp_status in ("OPTIMAL", "CONDITIONAL", "BLOCKED"):
            errs = check_small(case, res, {"activities": ["N"], "resource": "FERRALLISTA"} if cid == "RC06" else None)
            notes += errs
            ok &= not errs and res["validated"]
            if exp_obj is not None:
                ok &= res["objective_minutes"] == exp_obj
            ok &= res["solver_status"] == "OPTIMAL" and res["lower_bound_minutes"] == res["objective_minutes"] \
                and res["optimality_gap_minutes"] == 0
            got = {r["id"]: (r["start"], r["finish"]) for r in res["activities"]}
            if exp_sched:
                same = all(got.get(k) == v for k, v in exp_sched.items())
                ok &= same
                notes.append("reference dates match" if same else f"DATES DIFFER {[(k, got.get(k), v) for k, v in exp_sched.items() if got.get(k) != v]}")
            if exp_status == "CONDITIONAL":
                ok &= res["solver_scope"] == "conditional_projection" and bool(res["conditional_activities"])
                notes.append(f"conditional {res['conditional_activities']} scope {res['solver_scope']}")
            if exp_status == "BLOCKED":
                ok &= sorted(res["blocked_activities"]) == sorted(exp.get("blocked_activities", [])) \
                    and res["solver_scope"] == "unblocked_subset"
                notes.append(f"blocked {res['blocked_activities']} scope {res['solver_scope']}")
            if cid == "RC13a":
                rel = next(r for r in res["activities"] if r["id"] == "RELEASE")
                ok &= rel["finish"] == "2027-01-15T10:30+01:00"
                notes.append(f"RELEASE finish {rel['finish']} (R2-3 max(minimum, recorded))")
        else:
            code = (res.get("diagnostic") or {}).get("code", "")
            ok &= code == exp_code and not res["activities"] and not res["validated"]
            notes.append(f"diagnostic {code} vs {exp_code}")
        case_rows.append({"case_id": cid, "expected_status": exp_status, "status": res["status"],
                          "solver_status": res["solver_status"], "solver_scope": res.get("solver_scope"),
                          "expected_objective": exp_obj, "objective": res["objective_minutes"],
                          "lower_bound": res["lower_bound_minutes"], "timestamp_source": res.get("timestamp_source"),
                          "diagnostic": (res.get("diagnostic") or {}).get("code", ""),
                          "segments": sum(len(r["segments"]) for r in res["activities"]),
                          "independent_evidence": "; ".join(notes) or "per-minute check clean",
                          "verdict": "PASS" if ok else "FAIL"})

    # ---- frozen R0 handover runs (independent Stage 5.4A model)
    frozen = {}
    for tick, target in ((5, 14850), (15, 14880)):
        res = solve(frozen_r0(tick))
        errs, info = core.check_r0(tick, res)
        pour = next(a for a in res["activities"] if a["reference_id"] == "C-POUR")
        frozen[tick] = {"status": res["status"], "objective": res["objective_minutes"], "bound": res["lower_bound_minutes"],
                        "target": target, "independent_errors": errs, **info,
                        "cost": res["cost"]["total_direct_reference_eur"], "approvals": len(res["pending_approvals"]),
                        "c_pour_resources": pour["resources"], "real_project_eligible": res["real_project_eligible"],
                        "pass": res["status"] == "OPTIMAL" and res["objective_minutes"] == target == info["makespan"]
                        and not errs and res["cost"]["total_direct_reference_eur"] == 1172.5136
                        and pour["resources"].get("OFICIAL_1") == 1}

    # ---- 3/4. benchmarks via the normal CLI path
    bench_rows, bench_detail = [], {}
    manifest = json.loads((COR / "correction_manifest.json").read_text(encoding="utf-8"))
    for label in ("original", "holiday"):
        for version in ("v1.1", "v1.0"):
            cmd = [PY, "-B", "-m", "research.implementation.stage5_4b", "--demo", label]
            if version == "v1.0":
                cmd += ["--benchmark-version", "v1.0"]
            run = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, env=dict(os.environ))
            out = json.loads(run.stdout)
            rec = (manifest["corrected"] if version == "v1.1" else manifest["historical_preserved"])[label]
            src_path = PKG / rec["path"]
            src = json.loads(src_path.read_text(encoding="utf-8"))
            row = {"fixture": label, "version": version, "input_path": rec["path"], "input_sha256": sha(src_path),
                   "manifest_sha256_match": sha(src_path) == rec["sha256"],
                   "cli_benchmark_input_sha256": out.get("benchmark_input", {}).get("sha256"),
                   "coverage_sensitivity": out.get("benchmark_input", {}).get("coverage_sensitivity"),
                   "exit_code": run.returncode, "status": out["status"], "solver_status": out["solver_status"],
                   "objective": out["objective_minutes"], "lower_bound": out["lower_bound_minutes"],
                   "gap_minutes": out.get("optimality_gap_minutes"), "completion": out.get("completion_local"),
                   "activities": len(out["activities"]), "reservations_output": len(out.get("reservations", [])),
                   "source_activities": len(src["activities"]), "source_dependencies": len(src["dependencies"]),
                   "source_reservations": len(src["reservations"]),
                   "source_cost_sum": round(sum(a["cost_eur"] for a in src["activities"]), 6),
                   "result_cost": (out.get("cost") or {}).get("total_direct_reference_eur"),
                   "cpm_makespan": out["cpm_comparison"]["makespan_minutes"],
                   "cpm_conflicts": out["cpm_comparison"]["conflict_intervals"],
                   "cpm_pools": len(out["cpm_comparison"]["over_capacity_pools"]),
                   "resource_conflicts": len(out.get("resource_conflicts", [])) if out["activities"] else None}
            if version == "v1.1":
                c01.b.DATE_EXCEPTIONS = list(src["calendars"][0]["date_exceptions"])
                sched = {r["id"]: (r["start"], r["finish"]) for r in out["activities"]}
                checks = c01.check_with_coverage(src, sched)
                single = all(len(r["segments"]) == 1 for r in out["activities"])
                res_ok = all(rv["start"] == sched[d["start_event"]["activity_id"]][0]
                             and rv["finish"] == sched[d["release_condition"]["all_of"][0]["activity_id"]][1]
                             for rv, d in zip(out["reservations"], src["reservations"]))
                static = [r for r in c01.static_coverage(src, version) if r["static_status"].startswith("CONTRADICTION")]
                exp = json.loads((COR / label / "expected_results_v1.1.json").read_text(encoding="utf-8"))
                row.update(independent_checks=len(checks), independent_failed=sum(not r["passed"] for r in checks),
                           coverage_checks=sum(r["check"].startswith("reservation_covers") for r in checks),
                           single_segment=single, reservation_intervals_match=res_ok, static_contradictions=len(static),
                           expected_objective=exp["makespan_minutes"], expected_completion=exp["completion_local"])
                ok = (out["status"] == "OPTIMAL" and out["solver_status"] == "OPTIMAL"
                      and out["objective_minutes"] == out["lower_bound_minutes"] == exp["makespan_minutes"]
                      and out["completion_local"] == exp["completion_local"] and row["independent_failed"] == 0
                      and len(checks) == 350 and row["coverage_checks"] == 108 and single and res_ok
                      and row["activities"] == 70 and row["source_dependencies"] == 98 and row["reservations_output"] == 16
                      and row["result_cost"] == 5103.32664 == row["source_cost_sum"] and row["cpm_makespan"] == 16310
                      and row["cpm_conflicts"] == 29 and row["cpm_pools"] == 11 and row["resource_conflicts"] == 0
                      and row["manifest_sha256_match"] and row["coverage_sensitivity"] is False and run.returncode == 0
                      and out["real_project_eligible"] is False)
            else:
                d = out.get("diagnostic") or {}
                static = [r for r in c01.static_coverage(src, version) if r["static_status"].startswith("CONTRADICTION")]
                row.update(diagnostic=json.dumps(d), independent_static_contradictions=len(static),
                           diagnostic_reports_all=False if d.get("covered_activity_id") and len(static) > 1 else None)
                ok = (out["status"] == "INFEASIBLE" and out["solver_status"] is None and not out["activities"]
                      and not out["validated"] and d.get("code") == "STRUCTURAL_INFEASIBILITY"
                      and d.get("reservation_id", "").startswith("R-COLSET-C")
                      and d.get("covered_activity_id", "").endswith("-REBAR") and run.returncode == 1
                      and row["manifest_sha256_match"] and len(static) == 4
                      and sorted(c["reservation_id"] for c in d.get("contradictions", [])) == [f"R-COLSET-C{i}" for i in range(1, 5)])
            row["verdict"] = "PASS" if ok else "FAIL"
            bench_rows.append(row)

    # ---- 5. targeted corrections and input-state audit
    rc04 = normalize_reference(cases["RC04"])
    explicit_none = {"resource_id": "CRANE", "display_name": "CRANE", "capacity": 0, "kind": "equipment",
                     "explicit_none": True, "calendar": "project", "input_state": "hypothetical_fixture", "evidence_ref": None}

    def inj(base, fn):
        p = copy.deepcopy(base)
        fn(p)
        return solve(p)

    cd = {}
    r = inj(rc04, lambda p: (p["resources"].update(CRANE=dict(explicit_none)), p["activities"][4]["resources"].update(CRANE=1)))
    cd["CD01 explicit-none demanded"] = (r["status"], r["diagnostic"]["code"], r["status"] == "MODEL_INVALID" and r["diagnostic"]["code"] == "MISSING_INPUT")
    r = inj(rc04, lambda p: p["activities"][4].update(reserved_without_bcca_demand={"CREW_C": 1}))
    cd["CD02 mode fields without crew_mode"] = (r["status"], r["diagnostic"]["code"], r["diagnostic"]["code"] == "MODE_MISMATCH")
    r = inj(rc04, lambda p: p["pending_approvals"][0].update(status="APPROVED"))
    a = (r["status"], r["diagnostic"]["code"])
    r2 = inj(rc04, lambda p: p.update(fixture_exceptions=[{"anything": True}]))
    cd["CD03 approval/fixture metadata"] = (a, (r2["status"], r2["diagnostic"]["code"]),
                                            a[1] == "UNVERIFIED_APPROVAL" and r2["diagnostic"]["code"] == "UNVERIFIED_FIXTURE_EXCEPTION")
    r = inj(normalize_reference(cases["RC01"]), lambda p: p.update(horizon_end="2027-01-11T16:00"))
    cd["CD04 horizon diagnostic"] = (r["status"], r.get("diagnostic"), r["status"] == "INFEASIBLE" and (r.get("diagnostic") or {}).get("code") in ("HORIZON_EXHAUSTED", "INFEASIBLE") and "cause" in r["diagnostic"])
    rc06 = normalize_reference(cases["RC06"])
    r = inj(rc06, lambda p: p["calendar_exceptions"][0].pop("authorization_ref"))
    n = next(x for x in r["activities"] if x["id"] == "N")
    cd["CD05 ignored exception reported"] = (r["ignored_calendar_exceptions"], n["start"],
                                            bool(r["ignored_calendar_exceptions"]) and n["start"] == "2027-01-12T08:00+01:00")
    r0 = frozen_r0(5)
    nones = sorted(k for k, v in r0["resources"].items() if v.get("explicit_none"))
    p = copy.deepcopy(r0)
    p["resources"].pop("CONCRETE_DELIVERY", None)
    r = solve(p)
    cd["CD06 R0 explicit-none equipment"] = (nones, r["diagnostic"]["code"], nones == ["CONCRETE_DELIVERY", "CONCRETE_PUMP", "CRANE"] and r["diagnostic"]["code"] == "EXPLICIT_NONE_REQUIRED")
    cd["CD07 validator independence"] = ("validate() shares prepare(); acceptance uses this external checker", None, True)
    r = solve(normalize_reference(cases["RC01"]))
    cd["CD08 integer bounds"] = (type(r["lower_bound_minutes"]).__name__, type(r["optimality_gap_minutes"]).__name__,
                                 isinstance(r["lower_bound_minutes"], int) and isinstance(r["optimality_gap_minutes"], int))
    cd["CD09 timestamp source"] = (r["timestamp_source"], r["secondary_solver_status"], r["timestamp_source"] in ("primary", "secondary"))

    audit = {}
    for name, fn, want in [
        ("resource engineer_approved", lambda p: p["resources"]["CREW_A"].update(input_state="engineer_approved"), "UNVERIFIED_APPROVAL"),
        ("activity engineer_approved", lambda p: p["activities"][0].update(input_state="engineer_approved"), "UNVERIFIED_APPROVAL"),
        ("calendar engineer_approved", lambda p: p["project_calendar"].update(input_state="engineer_approved"), "UNVERIFIED_APPROVAL"),
        ("unregistered state string", lambda p: p["activities"][0].update(input_state="approved"), "INVALID_INPUT_STATE"),
        ("activity input_state absent", lambda p: p["activities"][0].pop("input_state"), "MISSING_INPUT"),
        ("resource evidence_ref absent", lambda p: p["resources"]["CREW_A"].pop("evidence_ref"), "MISSING_INPUT"),
        ("user_provided_project without evidence", lambda p: p["resources"]["CREW_A"].update(input_state="user_provided_project", evidence_ref=None), "MISSING_INPUT"),
        ("independently_measured without evidence", lambda p: p["activities"][0].update(input_state="independently_measured"), "MISSING_INPUT"),
        ("user_provided_project with evidence", lambda p: p["resources"]["CREW_A"].update(input_state="user_provided_project", evidence_ref="site memo 12"), "ACCEPT"),
        ("independently_measured with evidence", lambda p: p["activities"][0].update(input_state="independently_measured", evidence_ref="survey 3"), "ACCEPT"),
    ]:
        r = inj(rc04, fn)
        code = (r.get("diagnostic") or {}).get("code", "ACCEPT" if r["validated"] else r["status"])
        kept = None
        if want == "ACCEPT":
            res = r.get("resources", {}).get("CREW_A", {})
            act = next((x for x in r["activities"] if x["id"] == rc04["activities"][0]["id"]), {})
            kept = res.get("evidence_ref") == "site memo 12" or act.get("evidence_ref") == "survey 3"
        audit[name] = {"result": code, "expected": want, "evidence_preserved": kept,
                       "pass": code == want and (kept is not False)}
    rc05 = normalize_reference(cases["RC05a"])
    r = inj(rc05, lambda p: p["reservations"][0]["release_condition"].update(input_state="engineer_approved"))
    audit["reservation release engineer_approved"] = {"result": r["diagnostic"]["code"], "expected": "UNVERIFIED_APPROVAL",
                                                      "pass": r["diagnostic"]["code"] == "UNVERIFIED_APPROVAL"}
    rc12 = normalize_reference(cases["RC12a"])
    r = inj(rc12, lambda p: p["inspection_pass_events"][0].update(input_state="missing"))
    audit["hypothetical pass with missing state"] = {"result": r["diagnostic"]["code"], "expected": "MISSING_INPUT",
                                                    "pass": r["diagnostic"]["code"] == "MISSING_INPUT"}

    # ---- contract diagnostics not exercised by the reference cases
    contract = {}
    rc05a = normalize_reference(cases["RC05a"])
    rc10a = normalize_reference(cases["RC10a"])

    def code_of(r):
        return (r.get("diagnostic") or {}).get("code", "ACCEPT" if r["validated"] else r["status"])
    for name, base_p, fn, want in [
        ("V7 release not reachable from start", rc05a,
         lambda p: p["reservations"][0]["release_condition"]["all_of"].__setitem__(0, {"kind": "activity_finish", "activity_id": "E2-STRIP"}),
         "RESERVATION_UNRELEASED"),
        ("V8 covered activity succeeds release", rc05a,
         lambda p: (p["dependencies"].append({"predecessor": "E1-STRIP", "successor": "E2-FORM", "relation": "FS", "lag_minutes": 0, "lag_basis": "elapsed"}),
                    p["reservations"][0]["covers_activities"].append("E2-FORM")), "STRUCTURAL_INFEASIBILITY"),
        ("reservation quantity missing", rc05a, lambda p: p["reservations"][0].update(quantity=None), "MISSING_INPUT"),
        ("reshoring requested", rc05a, lambda p: p["reservations"][0]["release_condition"].update(reshoring="approved_with_ref"), "UNSUPPORTED_CONSTRAINT"),
        ("reservation on working resource", rc05a, lambda p: p["reservations"][0].update(resource_id="CREW_F"), "MODEL_INVALID"),
        ("split without authorization", rc10a, lambda p: next(a for a in p["activities"] if a["id"] == "S")["split"].pop("authorization_ref"), "SPLIT_NOT_AUTHORIZED"),
        ("split pour without cold-joint ref", rc10a,
         lambda p: (p["resources"].update(SUPPLY={"resource_id": "SUPPLY", "display_name": "SUPPLY", "capacity": 6, "unit": "m3/h", "kind": "supply_source", "calendar": "project", "input_state": "hypothetical_fixture", "evidence_ref": None, "explicit_none": False}),
                    next(a for a in p["activities"] if a["id"] == "S")["resources"].update(SUPPLY=6)), "SPLIT_NOT_AUTHORIZED"),
        ("supply rate missing", normalize_reference(cases["RC11a"]), lambda p: p["resources"]["SUPPLY"].update(capacity=None), "MISSING_INPUT"),
    ]:
        r = inj(base_p, fn)
        contract[name] = {"result": code_of(r), "expected": want, "pass": code_of(r) == want}
    r = solve(normalize_reference(cases["RC08c"]))
    contract["NO_ELIGIBLE_MODE detail"] = {"result": [r["diagnostic"]["code"], r["diagnostic"].get("mode_code")],
                                           "expected": "IMPOSSIBLE_CREW + NO_ELIGIBLE_MODE",
                                           "pass": r["diagnostic"].get("mode_code") == "NO_ELIGIBLE_MODE"}

    # ---- date-specific capacity overrides: SUT vs independent enumeration with dated caps
    t4.prepare = lambda case: prepare_dated(case)
    dated = []

    def dated_case(cid, rid, by_date, unit=None, extra=None):
        case = copy.deepcopy(cases[cid])
        case["case_id"] = f"{cid}+{rid}{by_date}"
        if unit:
            case["resources"][rid]["unit"] = unit
        case["resources"][rid]["capacity_by_date"] = by_date
        if extra:
            extra(case)
        return case

    scenarios = [
        ("reduction to zero (crew)", dated_case("RC01", "CREW_F", {"2027-01-11": 0}, "worker")),
        ("increase (crew 1->2)", dated_case("RC01", "CREW_F", {"2027-01-11": 2}, "worker")),
        ("equipment outage (crane)", dated_case("RC02", "CRANE", {"2027-01-11": 0}, "machine")),
        ("continuous reservation crossing a zero day", dated_case("RC05a", "FORMWORK_SET", {"2027-01-12": 0})),
        ("supply rate increase 6->12", dated_case("RC11a", "SUPPLY", {"2027-01-11": 12})),
        ("supply rate reduction 6->3", dated_case("RC11a", "SUPPLY", {"2027-01-11": 3})),
    ]
    for name, case in scenarios:
        expected = t4.solve_case({k: v for k, v in case.items() if k != "expected"})
        problem = normalize_reference({**case, "case_id": case["case_id"].split("+")[0]})
        problem["resources"][[k for k in case["resources"] if case["resources"][k].get("capacity_by_date")][0]]["capacity_by_date"] = \
            next(v["capacity_by_date"] for v in case["resources"].values() if v.get("capacity_by_date"))
        res = solve(problem)
        errs = check_small(case, res) if res["activities"] else ["no schedule"]
        dated.append({"scenario": name, "expected_status": expected["expected_status"],
                      "expected_makespan": expected.get("optimal_makespan_minutes"), "status": res["status"],
                      "makespan": res["objective_minutes"], "independent_errors": "; ".join(errs),
                      "pass": res["status"] == expected["expected_status"] and res["objective_minutes"] == expected.get("optimal_makespan_minutes") and not errs})
    t4.prepare = _prepare_policy
    # supply rate reduced below the per-pour draw: expected rejection or infeasible on that day only
    base = normalize_reference(cases["RC01"])
    for name, fn, want in [
        ("non-ISO date key", lambda p: p["resources"]["CREW_F"].update(unit="worker", capacity_by_date={"2027-1-11": 0}), "INVALID_CAPACITY_OVERRIDE"),
        ("negative value", lambda p: p["resources"]["CREW_F"].update(unit="worker", capacity_by_date={"2027-01-11": -1}), "INVALID_CAPACITY_OVERRIDE"),
        ("fractional value", lambda p: p["resources"]["CREW_F"].update(unit="worker", capacity_by_date={"2027-01-11": 1.5}), "INVALID_CAPACITY_OVERRIDE"),
        ("missing unit", lambda p: p["resources"]["CREW_F"].update(capacity_by_date={"2027-01-11": 0}), "INVALID_CAPACITY_OVERRIDE"),
        ("explicit-none acquiring capacity", lambda p: p["resources"].update(CRANE={**explicit_none, "unit": "machine", "capacity_by_date": {"2027-01-11": 1}}), "INVALID_CAPACITY_OVERRIDE"),
        ("explicit-none zero override", lambda p: p["resources"].update(CRANE={**explicit_none, "unit": "machine", "capacity_by_date": {"2027-01-11": 0}}), "ACCEPT"),
        ("not an object", lambda p: p["resources"]["CREW_F"].update(unit="worker", capacity_by_date=[["2027-01-11", 0]]), "INVALID_CAPACITY_OVERRIDE"),
    ]:
        r = inj(base, fn)
        code = (r.get("diagnostic") or {}).get("code", "ACCEPT" if r["validated"] else r["status"])
        dated.append({"scenario": name, "expected_status": want, "expected_makespan": None, "status": code,
                      "makespan": r["objective_minutes"], "independent_errors": "", "pass": code == want})
    with tempfile.TemporaryDirectory() as tmp:  # duplicate JSON keys through the CLI
        path = Path(tmp) / "dup.json"
        txt = json.dumps(normalize_reference(cases["RC01"]))
        txt = txt.replace('"capacity": 1, "kind": "renewable"', '"capacity": 1, "capacity": 2, "kind": "renewable"', 1)
        path.write_text(txt, encoding="utf-8")
        run = subprocess.run([PY, "-B", "-m", "research.implementation.stage5_4b", "--input", str(path)],
                             cwd=REPO, capture_output=True, text=True)
        code = json.loads(run.stdout)["diagnostic"]["code"]
        dated.append({"scenario": "conflicting duplicate key via CLI", "expected_status": "INVALID_JSON_INPUT",
                      "expected_makespan": None, "status": code, "makespan": None, "independent_errors": "",
                      "pass": code == "INVALID_JSON_INPUT" and run.returncode == 1})
    # direct boundary arithmetic: resource-local midnight (London), project-local for continuous, DST day
    madrid = ZoneInfo("Europe/Madrid")
    origin = local_epoch("2027-03-27T00:00", madrid)
    limit = local_epoch("2027-03-31T00:00", madrid)
    lon = {"kind": "labour_trade", "unit": "worker", "calendar": {"timezone": "Europe/London", "working_windows": []},
           "capacity_by_date": {"2027-03-29": 0}}
    got = capacity_periods(lon, 2, 1, madrid, origin, limit, 5)
    london = ZoneInfo("Europe/London")
    want_lon = (local_epoch("2027-03-29T00:00", london), local_epoch("2027-03-30T00:00", london))
    cont = {"kind": "reusable_asset", "unit": "set", "calendar": "continuous", "capacity_by_date": {"2027-03-28": 0}}
    got_c = capacity_periods(cont, 2, 1, madrid, origin, limit, 5)
    want_c = (local_epoch("2027-03-28T00:00", madrid), local_epoch("2027-03-29T00:00", madrid))
    tz_checks = {"resource_local_london": [list(x) for x in got], "expected_zero_window_london": list(want_lon),
                 "london_pass": any((a, b, v) == (*want_lon, 0) for a, b, v in got),
                 "continuous_project_local_dst_day": [list(x) for x in got_c], "expected_zero_window_madrid": list(want_c),
                 "dst_day_minutes": want_c[1] - want_c[0],
                 "continuous_pass": any((a, b, v) == (*want_c, 0) for a, b, v in got_c)}
    dated.append({"scenario": "timezone semantics (London resource; Madrid DST day continuous)", "expected_status": "boundaries",
                  "expected_makespan": None, "status": "computed", "makespan": None,
                  "independent_errors": "", "pass": tz_checks["london_pass"] and tz_checks["continuous_pass"] and tz_checks["dst_day_minutes"] == 1380})
    # validator rejects a schedule violating a dated capacity
    case = dated_case("RC01", "CREW_F", {"2027-01-11": 0}, "worker")
    problem = normalize_reference(cases["RC01"])
    problem["resources"]["CREW_F"].update(unit="worker", capacity_by_date={"2027-01-11": 0})
    good = solve(problem)
    bad = copy.deepcopy(good)
    act = next(x for x in bad["activities"] if x["id"] == "C")
    act.update(start="2027-01-11T08:00+01:00", finish="2027-01-11T10:50+01:00",
               segments=[["2027-01-11T08:00+01:00", "2027-01-11T10:50+01:00"]])
    try:
        validate(problem, bad)
        sut_rejects = False
    except Exception:  # noqa: BLE001
        sut_rejects = True
    mine = check_small(case, bad)
    dated.append({"scenario": "schedule on a zero-capacity day is rejected", "expected_status": "rejected by both",
                  "expected_makespan": None, "status": f"SUT rejects={sut_rejects}; independent={mine[:1]}",
                  "makespan": None, "independent_errors": "", "pass": sut_rejects and any("capacity CREW_F" in e for e in mine)})

    # split-pour supply allowance labelling
    split = normalize_reference(cases["RC10a"])
    s_act = next(x for x in split["activities"] if x["id"] == "S")
    split["resources"]["SUPPLY"] = {"resource_id": "SUPPLY", "display_name": "SUPPLY", "capacity": 6, "unit": "m3/h",
                                    "kind": "supply_source", "calendar": "project", "input_state": "hypothetical_fixture",
                                    "evidence_ref": None, "explicit_none": False, "max_volume_per_day_m3": 200}
    s_act["resources"]["SUPPLY"] = 6
    s_act["split"].update(restart_overhead_minutes=30, cold_joint_authorization_ref="HYP cold joint")
    r = solve(split)
    seg = next(x for x in r["activities"] if x["id"] == "S")["segments"]
    seg_m = [epoch(b) - epoch(a) for a, b in seg]
    productive = sum(seg_m) - 30 * (len(seg_m) - 1)
    physical = productive / 60 * 6
    reported = sum(float(Fraction(row["total_capacity_allowance_m3"])) for row in r.get("supply_checks", []))
    supply_eval = {"status": r["status"], "segments_minutes": seg_m, "productive_minutes": productive,
                   "physical_volume_m3": physical, "reported_draw_m3": reported,
                   "fields": sorted(r.get("supply_checks", [{}])[0].keys()) if r.get("supply_checks") else [],
                   "occupancy_basis": sorted({x["occupancy_basis"] for x in r.get("resource_occupancy", []) if x["resource_id"] == "SUPPLY"})}

    # ---- 6. regression and preservation
    tests_hist = subprocess.run([str(REPO / ".venv/Scripts/python.exe"), "-B", "-m", "unittest", "discover", "-s", "tests",
                                 "-p", "test_stage5_*.py"], cwd=REPO, capture_output=True, text=True)
    tests_opt = subprocess.run([PY, "-B", "-m", "unittest", "research.implementation.stage5_4b.test_engine",
                                "research.implementation.stage5_4b.test_advanced", "research.implementation.stage5_4b.test_review",
                                "research.implementation.stage5_4b.test_closure"], cwd=REPO, capture_output=True, text=True)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "r"
        subprocess.run([PY, "-B", "-m", "pmi_core.scheduling", "--config",
                        "research/implementation/stage5_4a/controlled_schedule_inputs.json", "--output", str(out)],
                       cwd=REPO, capture_output=True, text=True)
        exports = sorted(p.name for p in out.iterdir())
        same = [f for f in exports if (REPO / "research/implementation/stage5_4a" / f).read_bytes() == (out / f).read_bytes()]
    t7m = json.loads((PKG / "deliverable_manifest.json").read_text(encoding="utf-8"))
    t7_changed = [e["path"] for e in t7m["files"] if sha(PKG / e["path"]) != e["sha256"]]
    c01_changed = [k for k, v in manifest["files"].items() if sha(COR / k) != v]
    hist_ok = all(sha(PKG / v["path"]) == v["sha256"] for v in manifest["historical_preserved"].values())
    reg = REPO / "research/validation/engineering_approval_review/priority_approval_register.csv"
    rows88 = approvals()
    preservation = {
        "tests_historical": tests_hist.stderr.strip().splitlines()[-3:], "tests_historical_ok": tests_hist.returncode == 0,
        "tests_optimizer": tests_opt.stderr.strip().splitlines()[-3:], "tests_optimizer_ok": tests_opt.returncode == 0,
        "stage5_4a_exports_identical": f"{len(same)}/{len(exports)}",
        "register_sha256": sha(reg), "register_expected": "d86a26cea516c10a38d97c5d82b5ca03d4af940f01a9bdcdd359bdac3111ab23",
        "approvals": len(rows88), "approvals_pending": sum(r["status"] == "PENDING" for r in rows88),
        "task7_manifest_changed": t7_changed, "c01_manifest_changed": c01_changed, "c01_historical_hashes_ok": hist_ok,
    }
    ended = {"head": git("rev-parse", "HEAD").strip(), "status": git("status", "--porcelain").splitlines(), "impl": impl_hashes()}
    stability = {"start_head": started["head"], "end_head": ended["head"],
                 "implementation_unchanged": started["impl"] == ended["impl"],
                 "head_unchanged": started["head"] == ended["head"],
                 "status_start": started["status"], "status_end": ended["status"]}

    # ---- write
    def wcsv(name, rows):
        with (OUT / name).open("w", encoding="utf-8-sig", newline="") as f:
            keys = list(dict.fromkeys(k for r in rows for k in r))
            w = csv.DictWriter(f, keys)
            w.writeheader()
            w.writerows(rows)
    wcsv("independent_case_results.csv", case_rows)
    wcsv("independent_benchmark_results.csv", bench_rows)
    evidence = {"stability": stability, "cases_pass": sum(r["verdict"] == "PASS" for r in case_rows),
                "cases_total": len(case_rows), "benchmarks": [{k: r[k] for k in ("fixture", "version", "verdict")} for r in bench_rows],
                "frozen_r0": frozen, "targeted_corrections": cd, "input_state_audit": audit, "contract_diagnostics": contract, "date_capacity": dated, "timezone_checks": tz_checks,
                "split_pour_supply": supply_eval, "preservation": preservation}
    (OUT / "verification_evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False, default=str) + "\n",
                                                    encoding="utf-8")
    print(json.dumps({k: evidence[k] for k in ("stability", "cases_pass", "cases_total", "benchmarks")}, indent=1))
    for r in case_rows:
        if r["verdict"] != "PASS" or r["case_id"] in ("RC05a", "RC10a", "RC10c", "RC11a", "RC12b", "RC12c", "RC13a", "RC13b"):
            print(r["case_id"], r["verdict"], r["status"], r["objective"], r["expected_objective"], r["independent_evidence"][:160])
    for r in bench_rows:
        print({k: r.get(k) for k in ("fixture", "version", "verdict", "status", "objective", "independent_checks", "independent_failed", "diagnostic", "exit_code")})
    print(json.dumps({"cd": cd, "audit": audit}, indent=1, default=str))
    for d in dated:
        print(d)
    print(json.dumps(supply_eval, indent=1))
    print(json.dumps(preservation, indent=1))


if __name__ == "__main__":
    main()
