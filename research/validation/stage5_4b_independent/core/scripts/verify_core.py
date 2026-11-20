"""Independent verification of Stage 5.4B.1 (CP-SAT core). Run with .venv-planning from the repo root.

System under test: research.implementation.stage5_4b (solve, fixtures). Oracles used here do NOT share
its preprocessing: expected values come from the Task 4 exhaustive engine re-run under the R2 default
calendar policy, and every returned schedule is re-checked minute by minute from the ORIGINAL case
JSON (not the normalized problem) or, for frozen R0, from the independent Stage 5.4A model.
"""

import copy
import csv
import hashlib
import json
import math
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
REPO = HERE.parents[4]
PKG = REPO / "research/validation/stage5_4a_independent_verification"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(PKG / "scripts"))

import research.implementation.stage5_4b.engine as engine  # noqa: E402  (system under test)
from research.implementation.stage5_4b.engine import solve  # noqa: E402
from research.implementation.stage5_4b.fixtures import frozen_r0, normalize_reference, reference_cases  # noqa: E402
import build_task7_cases as t7  # noqa: E402  (patches the Task 4 engine with the R2 default policy)
import independent_cpm as ind  # noqa: E402

t4 = t7.t4
DEFERRED = {"RC05a", "RC05b", "RC10a", "RC10c", "RC11a", "RC11b", "RC12a", "RC12b", "RC12c", "RC12d",
            "RC12e", "RC13a", "RC13b"}
DEFERRED_FEATURE = {"RC05a": "reservations", "RC05b": "reservations", "RC10a": "interruption",
                    "RC10c": "interruption", "RC11a": "resource type", "RC11b": "resource type",
                    "RC12a": "inspection_pass_events", "RC12b": "inspection_pass_events",
                    "RC12c": "inspection_pass_events", "RC12d": "inspection_pass_events",
                    "RC12e": "inspection_pass_events", "RC13a": "strength_events", "RC13b": "strength_events"}


def epoch(text):
    return int(datetime.fromisoformat(text).timestamp() // 60)


# --------------------------------------------------------------------------- independent checker
def is_open(cal, project, minute, zone):
    if cal == "continuous":
        return True
    cal = project if cal == "project" else cal
    loc = datetime.fromtimestamp(minute * 60, zone)
    day = loc.date().isoformat()
    if day in cal.get("date_exceptions", []):
        return False
    hm = loc.strftime("%H:%M")
    windows = cal.get("date_overrides", {}).get(day)
    if windows is None:
        windows = [w for w in cal["working_windows"] if w["weekday"] == loc.isoweekday()]
    return any(w["start"] <= hm < w["end"] for w in windows)


def check_case(case, result, exception=None):
    """Check a solver schedule against the original reference case, minute by minute."""
    zone = ZoneInfo(case["timezone"])
    tick = case["tick_minutes"]
    origin = epoch(datetime.fromisoformat(case["project_start"]).replace(tzinfo=zone).isoformat())
    acts = {a["id"]: a for a in case["activities"]}
    rows = {r["id"]: r for r in result["activities"]}
    errors = []
    if set(rows) != set(acts):
        return [f"activity set differs: {sorted(set(rows) ^ set(acts))}"]
    span = {k: (epoch(r["start"]), epoch(r["finish"])) for k, r in rows.items()}
    for k, a in acts.items():
        s, f = span[k]
        want = math.ceil(round(a["duration_minutes"] / tick, 9)) * tick
        if f - s != want:
            errors.append(f"{k}: duration {f - s} != {want}")
        if (s - origin) % tick:
            errors.append(f"{k}: off grid")
        if rows[k]["segments"] != [[rows[k]["start"], rows[k]["finish"]]]:
            errors.append(f"{k}: unexpected segments")
        if a.get("not_before") and s < epoch(datetime.fromisoformat(a["not_before"]).replace(tzinfo=zone).isoformat()):
            errors.append(f"{k}: before not_before")
        if a["kind"] == "elapsed_hold":
            continue
        cals = [case["project_calendar"] if not (exception and k in exception["activities"])
                else case["resources"][exception["resource"]]["calendar"]]
        cals += [case["resources"][r].get("calendar", "project") for r in a.get("resources", {})]
        for m in range(s, f):
            if not all(is_open(c, case["project_calendar"], m, zone) for c in cals):
                errors.append(f"{k}: closed calendar at {datetime.fromtimestamp(m * 60, zone):%Y-%m-%d %H:%M}")
                break
            if a.get("allowed_hours"):
                hm = datetime.fromtimestamp(m * 60, zone).strftime("%H:%M")
                if not any(lo <= hm < hi for lo, hi in a["allowed_hours"]):
                    errors.append(f"{k}: outside allowed_hours")
                    break
    for d in case["dependencies"]:
        lag = math.ceil(round(d["lag_minutes"] / tick, 9)) * tick
        if span[d["successor"]][0] < span[d["predecessor"]][1] + lag:
            errors.append(f"precedence {d['predecessor']}->{d['successor']}")
    load = defaultdict(lambda: defaultdict(int))
    for k, a in acts.items():
        for r, q in a.get("resources", {}).items():
            for m in range(*span[k]):
                load[r][m] += q
    for r, per in load.items():
        cap = case["resources"][r]["capacity"]
        peak = max(per.values())
        if peak > cap:
            errors.append(f"capacity {r}: {peak} > {cap}")
    finish = max(f for _, f in span.values())
    for d in case.get("deadlines", []):
        lim = epoch(datetime.fromisoformat(d["latest_finish"]).replace(tzinfo=zone).isoformat())
        got = finish if d["activity"] == "PROJECT" else span[d["activity"]][1]
        if got > lim:
            errors.append(f"deadline {d['activity']}")
    if result["objective_minutes"] != finish - origin:
        errors.append(f"objective {result['objective_minutes']} != makespan {finish - origin}")
    return errors


def check_r0(tick, result):
    """Re-check frozen R0 output against the independent Stage 5.4A model (aliases, BCCA names)."""
    h, prep, acts, edges_a, _ = ind.build_model(tick)
    edges = ind.final_edges(edges_a)
    zone = ZoneInfo(prep["calendar"]["timezone"])
    holidays = set(prep["calendar"]["date_exceptions"])
    names = {"OF1_ENCOFRADOR": "OF. 1ª ENCOFRADOR", "PEON_ESPECIAL": "PEÓN ESPECIAL",
             "OF1_FERRALLISTA": "OF. 1ª FERRALLISTA", "OFICIAL_1": "OFICIAL 1ª"}
    rows = {r["reference_id"]: r for r in result["activities"]}
    errors = []
    if set(rows) != set(acts):
        return [f"activity set differs {sorted(set(rows) ^ set(acts))}"], None
    span = {k: (epoch(r["start"]), epoch(r["finish"])) for k, r in rows.items()}

    def working(m, pour):
        loc = datetime.fromtimestamp(m * 60, zone)
        hm = loc.strftime("%H:%M")
        return (loc.isoweekday() <= 5 and loc.date().isoformat() not in holidays
                and "08:00" <= hm < ("14:00" if pour else "16:00"))

    for k, a in acts.items():
        s, f = span[k]
        if f - s != a["dur"]:
            errors.append(f"{k}: duration {f - s} != {a['dur']}")
        res = {names.get(r, r): q for r, q in rows[k]["resources"].items()}
        if res != a["res"]:
            errors.append(f"{k}: occupancy {res} != independent {a['res']}")
        if a["kind"] != "elapsed" and not all(working(m, a["pour"]) for m in range(s, f)):
            errors.append(f"{k}: calendar")
    for x, y in edges:
        if span[y][0] < span[x][1]:
            errors.append(f"precedence {x}->{y}")
    for x in "CBS":
        if span[f"{x}-STRIKE"][0] != span[f"{x}-POUR"][1]:
            errors.append(f"{x}-STRIKE not anchored to pour finish")
    load = defaultdict(lambda: defaultdict(int))
    for k, a in acts.items():
        for r, q in a["res"].items():
            for m in range(*span[k]):
                load[r][m] += q
    caps = prep["resource_capacity_by_trade"]
    for r, per in load.items():
        if max(per.values()) > caps[r]:
            errors.append(f"capacity {r}")
    origin = min(s for s, _ in span.values())
    makespan = max(f for _, f in span.values()) - origin
    if makespan != result["objective_minutes"]:
        errors.append("objective mismatch")
    cost = round(sum(a["cost"] or 0 for a in acts.values()), 6)
    return errors, {"independent_cpm_makespan": ind.schedule(tick, edges)["makespan"], "makespan": makespan,
                    "independent_cost_sum": cost}


def default_policy_expected(case):
    """Expected outcome from the Task 4 exhaustive engine under the R2 default calendar policy."""
    c = {k: v for k, v in case.items() if k != "expected"}
    if c["case_id"] == "RC06":
        c["calendar_policy"] = t7.EXCEPTION_POLICY
    if c["case_id"].startswith("R0-"):
        return t4.solve_fixture(c)
    return t4.solve_case(c)


# --------------------------------------------------------------------------- main
def main():
    cases = reference_cases()
    case_rows, findings = [], {}
    for cid, case in sorted(cases.items()):
        if cid == "DEMO-H1":
            continue
        problem = normalize_reference(case)
        result = solve(problem)
        row = {"case_id": cid, "status": result["status"], "solver_status": result["solver_status"],
               "diagnostic": (result.get("diagnostic") or {}).get("code", ""),
               "objective_minutes": result["objective_minutes"], "lower_bound_minutes": result["lower_bound_minutes"],
               "gap": result["optimality_gap"], "validated": result["validated"],
               "completion": result.get("completion_local", "")}
        if cid in DEFERRED:
            msg = (result.get("diagnostic") or {}).get("message", "")
            ok = (result["status"] == "MODEL_INVALID" and row["diagnostic"] == "UNSUPPORTED_CONSTRAINT"
                  and result["solver_status"] is None and not result["activities"]
                  and DEFERRED_FEATURE[cid] in msg)
            row.update(expected_status="deferred (reject before solve)", expected_objective="",
                       independent_check="rejection names the deferred feature" if ok else f"UNEXPECTED: {msg}",
                       verdict="PASS" if ok else "FAIL")
        else:
            exp = default_policy_expected(case)
            row.update(expected_status=exp["expected_status"], expected_objective=exp.get("optimal_makespan_minutes") or "",
                       expected_code=exp.get("preflight_code", ""))
            ok = result["status"] == exp["expected_status"]
            notes = []
            if exp["expected_status"] == "OPTIMAL":
                ok &= result["objective_minutes"] == exp["optimal_makespan_minutes"]
                ok &= result["lower_bound_minutes"] == result["objective_minutes"] and result["optimality_gap"] == 0
                ok &= result["solver_status"] == "OPTIMAL" and result["validated"]
                exc = {"activities": ["N"], "resource": "FERRALLISTA"} if cid == "RC06" else None
                errs = check_case(case, result, exc)
                notes += errs
                ok &= not errs
                if exp.get("unique_optimal_schedule"):
                    want = {r["id"]: (r["start"], r["finish"]) for r in exp["reference_schedule"]}
                    got = {r["id"]: (r["start"], r["finish"]) for r in result["activities"]}
                    same = want == got
                    ok &= same
                    notes.append("unique schedule matches" if same else "UNIQUE SCHEDULE DIFFERS")
            else:
                same_code = row["diagnostic"] == exp.get("preflight_code")
                ok &= same_code and not result["activities"]
                notes.append(f"diagnostic {row['diagnostic']} vs expected {exp.get('preflight_code')}")
            row.update(independent_check="; ".join(notes) or "per-minute check clean", verdict="PASS" if ok else "FAIL")
        case_rows.append(row)

    # ---- frozen R0
    r0 = {}
    for tick, target in ((5, 14850), (15, 14880)):
        problem = frozen_r0(tick)
        result = solve(problem)
        errs, info = check_r0(tick, result)
        pend = result["pending_approvals"]
        cost_sum = round(sum(a.get("reference_cost_eur") or 0 for a in result["activities"]), 6)
        pour = next(a for a in result["activities"] if a["reference_id"] == "C-POUR")
        r0[tick] = {"status": result["status"], "solver_status": result["solver_status"],
                    "objective": result["objective_minutes"], "lower_bound": result["lower_bound_minutes"],
                    "gap": result["optimality_gap"], "completion": result["completion_local"],
                    "target": target, "independent_errors": errs, **info,
                    "cost_total": result["cost"]["total_direct_reference_eur"], "cost_activity_sum": cost_sum,
                    "dependencies": len(problem["dependencies"]),
                    "approvals": len(pend), "approvals_pending": sum(r["status"] == "PENDING" for r in pend),
                    "approval_ids_unique": len({r["approval_id"] for r in pend}),
                    "c_pour_resources": pour["resources"], "c_pour_reserved": pour.get("reserved_without_bcca_demand"),
                    "real_project_eligible": result["real_project_eligible"],
                    "fixture_exceptions": [e["id"] for e in result.get("fixture_exceptions", [])]}

    # ---- status/bound integrity
    integrity = {}

    class StarvedTieBreak(engine.cp_model.CpSolver):
        count = 0

        def solve(self, model, *a, **k):
            StarvedTieBreak.count += 1
            if StarvedTieBreak.count == 2:  # the secondary earlier-start solve
                self.parameters.max_time_in_seconds = 1e-9
            return super().solve(model, *a, **k)

    original_solver = engine.cp_model.CpSolver
    for label, prob in (("RC01", normalize_reference(cases["RC01"])), ("R0-5", frozen_r0(5))):
        normal = solve(copy.deepcopy(prob))
        StarvedTieBreak.count = 0
        engine.cp_model.CpSolver = StarvedTieBreak
        try:
            starved = solve(copy.deepcopy(prob))
        finally:
            engine.cp_model.CpSolver = original_solver
        integrity[f"tie_break_starved_{label}"] = {
            "normal": [normal["status"], normal["objective_minutes"], normal["lower_bound_minutes"]],
            "starved": [starved["status"], starved["objective_minutes"], starved["lower_bound_minutes"],
                        starved["validated"]],
            "same_status_objective_bound": (normal["status"], normal["objective_minutes"], normal["lower_bound_minutes"])
            == (starved["status"], starved["objective_minutes"], starved["lower_bound_minutes"]),
            "secondary_changed_dates": [r["start"] for r in normal["activities"]] != [r["start"] for r in starved["activities"]]}
    for label, prob in (("R0-5", frozen_r0(5)), ("RC09", normalize_reference(cases["RC09"])),
                        ("RC01", normalize_reference(cases["RC01"]))):
        for limit in (1e-6, 1e-3, 0.02):
            r = solve(copy.deepcopy(prob), time_limit=limit)
            consistent = (
                (r["status"] == "OPTIMAL" and r["lower_bound_minutes"] == r["objective_minutes"] and r["validated"])
                or (r["status"] == "FEASIBLE" and r["validated"] and r["lower_bound_minutes"] <= r["objective_minutes"]
                    and r["optimality_gap"] >= 0)
                or (r["status"] == "UNKNOWN" and not r["activities"] and not r["validated"] and r["objective_minutes"] is None))
            integrity[f"time_limit_{label}_{limit}"] = {"status": r["status"], "objective": r["objective_minutes"],
                                                         "bound": r["lower_bound_minutes"], "gap": r["optimality_gap"],
                                                         "validated": r["validated"], "consistent": consistent}

    # ---- deadline diagnostics
    deadline = {}
    r = solve(normalize_reference(cases["RC07a"]))
    deadline["RC07a"] = {"status": r["status"], "solver_status": r["solver_status"], "diagnostic": r.get("diagnostic")}
    p = normalize_reference(cases["RC01"])
    p["deadlines"] = [{"activity": "project", "latest_finish": "2027-01-11T09:00"}]
    r = solve(p)
    deadline["preflight_precedence"] = {"status": r["status"], "solver_status": r["solver_status"],
                                        "code": r["diagnostic"]["code"]}
    p = normalize_reference(cases["RC01"])
    p["deadlines"] = [{"activity": "A", "latest_finish": "2027-01-11T11:50"},
                      {"activity": "B", "latest_finish": "2027-01-11T11:20"}]
    r = solve(p)
    deadline["capacity_driven_two_deadlines"] = {"status": r["status"], "solver_status": r["solver_status"],
                                                 "diagnostic": r.get("diagnostic")}
    p = normalize_reference(cases["RC01"])
    p["horizon_end"] = "2027-01-11T16:00"
    r = solve(p)
    deadline["horizon_infeasible_no_deadline"] = {"status": r["status"], "solver_status": r["solver_status"],
                                                  "diagnostic": r.get("diagnostic")}

    # ---- unsupported constraints entering through normalized JSON
    base = normalize_reference(cases["RC04"])
    def m(fn):
        p = copy.deepcopy(base)
        fn(p)
        return p
    injections = [
        ("unknown top-level key", lambda p: p.update(supply_rate=6), "reject"),
        ("non-empty reservations", lambda p: p.update(reservations=[{"reservation_id": "X"}]), "reject"),
        ("non-empty inspection_pass_events", lambda p: p.update(inspection_pass_events=[{"event_id": "E"}]), "reject"),
        ("non-empty strength_events", lambda p: p.update(strength_events=[{"event_id": "E"}]), "reject"),
        ("non-empty hypothetical_strength_events", lambda p: p.update(hypothetical_strength_events={"x": 1}), "reject"),
        ("non-empty release_events", lambda p: p.update(release_events={"x": 1}), "reject"),
        ("non-empty supply_sources", lambda p: p.update(supply_sources=[{"id": "S"}]), "reject"),
        ("split_allowed with full policy", lambda p: p["activities"][0].update(interruption="split_allowed", split={"authorization_ref": "x", "max_segments": 2, "min_segment_minutes": 60}), "reject"),
        ("split_allowed without authorization", lambda p: p["activities"][0].update(interruption="split_allowed"), "reject"),
        ("activity unknown field", lambda p: p["activities"][0].update(cold_joint=True), "reject"),
        ("activity release_event_id field", lambda p: p["activities"][0].update(release_event_id="EV"), "reject"),
        ("activity kind strength_release", lambda p: p["activities"][0].update(kind="strength_release"), "reject"),
        ("dependency SS", lambda p: p["dependencies"][0].update(relation="SS"), "reject"),
        ("dependency working lag basis", lambda p: p["dependencies"][0].update(lag_basis="working"), "reject"),
        ("dependency negative lag", lambda p: p["dependencies"][0].update(lag_minutes=-5), "reject"),
        ("dependency extra field", lambda p: p["dependencies"][0].update(condition="x"), "reject"),
        ("resource kind reservation", lambda p: p["resources"]["CREW_A"].update(kind="reservation"), "reject"),
        ("resource unit m3/h", lambda p: p["resources"]["CREW_A"].update(unit="m3/h"), "reject"),
        ("resource calendar continuous", lambda p: p["resources"]["CREW_A"].update(calendar="continuous"), "reject"),
        ("resource capacity_by_date", lambda p: p["resources"]["CREW_A"].update(capacity_by_date={"2027-01-11": 0}), "reject"),
        ("calendar extra key", lambda p: p["resources"]["INSPECTOR"]["calendar"].update(note="x"), "reject"),
        ("calendar exception extra key", lambda p: p.update(calendar_exceptions=[{"exception_id": "E", "activity_ids": ["R1"], "replaces": "project_calendar", "replacement_resource_id": "INSPECTOR", "authorization_ref": "x", "input_state": "hypothetical_fixture", "extra": 1}]), "reject"),
        ("calendar exception without authorization", lambda p: p.update(calendar_exceptions=[{"exception_id": "E", "activity_ids": ["R1"], "replaces": "project_calendar", "replacement_resource_id": "INSPECTOR", "input_state": "hypothetical_fixture"}]), "default policy (R2)"),
        ("objective minimize_cost", lambda p: p.update(objective="minimize_cost"), "reject"),
        ("deadline extra key", lambda p: p.update(deadlines=[{"activity": "project", "latest_finish": "2027-01-12T16:00", "soft": True}]), "reject"),
        ("tick 7", lambda p: p.update(tick_minutes=7), "reject"),
        ("scope real project", lambda p: p.update(scope="real_project"), "reject"),
        ("resource input_state missing", lambda p: p["resources"]["CREW_A"].update(input_state="missing"), "reject"),
        ("activity input_state missing", lambda p: p["activities"][0].update(input_state="missing"), "reject"),
        ("elapsed hold with allowed_hours", lambda p: p["activities"].append({"id": "H", "kind": "elapsed_hold", "duration_minutes": 60, "resources": {}, "allowed_hours": [["08:00", "10:00"]]}), "reject"),
        ("required equipment undeclared", lambda p: p["activities"][4].update(required_equipment=["CRANE"]), "reject EXPLICIT_NONE_REQUIRED"),
        ("required equipment declared explicit none", lambda p: (p["activities"][4].update(required_equipment=["CRANE"]), p["resources"].update(CRANE={"resource_id": "CRANE", "display_name": "CRANE", "capacity": 0, "kind": "equipment", "explicit_none": True, "calendar": "project", "input_state": "hypothetical_fixture"})), "accept"),
        ("explicit-none resource demanded", lambda p: (p["resources"].update(CRANE={"resource_id": "CRANE", "display_name": "CRANE", "capacity": 0, "kind": "equipment", "explicit_none": True, "calendar": "project", "input_state": "hypothetical_fixture"}), p["activities"][4]["resources"].update(CRANE=1)), "reject (contract V2: MISSING_INPUT)"),
        ("reserved_without_bcca_demand without crew_mode", lambda p: p["activities"][4].update(reserved_without_bcca_demand={"CREW_C": 1}), "reject or enforce V5-R2"),
        ("fixture_exceptions arbitrary content", lambda p: p.update(fixture_exceptions=[{"anything": True}]), "pass-through metadata"),
        ("pending_approvals marked APPROVED", lambda p: p.update(pending_approvals=[{"approval_id": "AP-X", "status": "APPROVED"}]), "pass-through metadata"),
    ]
    inj_rows = []
    for name, fn, want in injections:
        r = solve(m(fn))
        inj_rows.append({"injection": name, "expected": want, "status": r["status"],
                         "code": (r.get("diagnostic") or {}).get("code", ""), "validated": r["validated"],
                         "accepted_and_scheduled": bool(r["activities"])})
    # CLI --input path
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "injected.json"
        path.write_text(json.dumps(m(lambda p: p.update(reservations=[{"reservation_id": "X"}]))), encoding="utf-8")
        cli = subprocess.run([sys.executable, "-B", "-m", "research.implementation.stage5_4b", "--input", str(path)],
                             cwd=REPO, capture_output=True, text=True)
        out = json.loads(cli.stdout)
        inj_rows.append({"injection": "CLI --input with reservations", "expected": "reject, exit 1", "status": out["status"],
                         "code": out["diagnostic"]["code"], "validated": out["validated"],
                         "accepted_and_scheduled": bool(out["activities"]), "exit_code": cli.returncode})

    # ---- approvals and preservation
    reg = REPO / "research/validation/engineering_approval_review/priority_approval_register.csv"
    add = PKG / "engineering_approval_addendum.csv"
    pres = json.loads((PKG / "preservation_verification.json").read_text(encoding="utf-8"))
    manifest = json.loads((PKG / "deliverable_manifest.json").read_text(encoding="utf-8"))
    changed = [e["path"] for e in manifest["files"]
               if hashlib.sha256((PKG / e["path"]).read_bytes()).hexdigest() != e["sha256"]]
    status = subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True).stdout
    with reg.open(encoding="utf-8-sig") as f:
        reg_rows = list(csv.DictReader(f))
    with add.open(encoding="utf-8-sig") as f:
        add_rows = list(csv.DictReader(f))
    preservation = {"register_sha256": hashlib.sha256(reg.read_bytes()).hexdigest(),
                    "register_sha256_task7": pres["original_approvals"]["sha256"],
                    "register_rows_pending": [len(reg_rows), sum(r["status"] == "PENDING" for r in reg_rows)],
                    "addendum_rows_pending": [len(add_rows), sum(r["status"] == "PENDING" for r in add_rows)],
                    "task7_manifest_files_changed": changed, "git_status_porcelain": status.splitlines()}

    with (OUT / "case_results.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fields = sorted({k for r in case_rows for k in r}, key=lambda k: list(case_rows[0]).index(k) if k in case_rows[0] else 99)
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows(case_rows)
    with (OUT / "injection_results.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, ["injection", "expected", "status", "code", "validated", "accepted_and_scheduled", "exit_code"])
        w.writeheader()
        w.writerows(inj_rows)
    summary = {"head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip(),
               "ortools": engine.cp_model.__name__ and __import__("ortools").__version__,
               "cases_pass": sum(r["verdict"] == "PASS" for r in case_rows), "cases_total": len(case_rows),
               "applicable_pass": sum(r["verdict"] == "PASS" for r in case_rows if r["case_id"] not in DEFERRED),
               "deferred_pass": sum(r["verdict"] == "PASS" for r in case_rows if r["case_id"] in DEFERRED),
               "frozen_r0": r0, "integrity": integrity, "deadlines": deadline, "preservation": preservation}
    (OUT / "verification_results.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n",
                                                   encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("head", "cases_pass", "cases_total", "applicable_pass", "deferred_pass")}))
    for r in case_rows:
        print(r["case_id"], r["verdict"], r["status"], r["objective_minutes"], r.get("expected_objective"), r["independent_check"][:90])
    print(json.dumps(r0, indent=1, ensure_ascii=False, default=str)[:2500])
    print(json.dumps(integrity, indent=1))
    print(json.dumps(deadline, indent=1, default=str)[:3000])
    for r in inj_rows:
        print(r)
    print(json.dumps(preservation, indent=1))


if __name__ == "__main__":
    main()
