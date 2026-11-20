"""Correction C01 (fixture v1.1): column formwork reservation coverage under the cage-first method.

* Statically analyses every declared reservation (covered activity must lie between the start-event activity
  and the release activity in the precedence graph) in every reference file of the package.
* Writes corrected v1.1 copies of the original and holiday demo fixtures that remove ONLY C*-REBAR from the
  four R-COLSET-* coverage lists. Historical files are read, never written.
* Verifies the diff is exactly those four removals plus a correction block.
* Recomputes both fixtures from the corrected JSON alone (independent engine; lower bound + serial schedule
  generation) and re-checks schedules with a coverage-aware checker (V8), which also rejects the originals.
"""

import copy
import csv
import hashlib
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

if os.environ.get("PYTHONHASHSEED") != "0":  # deterministic representative schedules (Task 7 RD01)
    sys.exit(subprocess.run([sys.executable, "-B", *sys.argv], env=dict(os.environ, PYTHONHASHSEED="0")).returncode)

HERE = Path(__file__).resolve().parent
COR = HERE.parent
PKG = HERE.parents[2]
REPO = HERE.parents[5]
DEMO = PKG / "controlled_resource_demo"
HOL = PKG / "controlled_resource_demo_holiday_sensitivity"
sys.path.insert(0, str(DEMO / "scripts"))
import build_controlled_resource_demo as b  # noqa: E402  (own independent engine; not Agent 1 code)

VERSION = "v1.1"
COLUMN_RES = {f"R-COLSET-C{i}" for i in range(1, 5)}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))


def write_json(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv(p, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)


# --------------------------------------------------------------------------- static coverage (V8)
def closure(edges):
    succ = defaultdict(set)
    for a, b_ in edges:
        succ[a].add(b_)
    memo = {}

    def reach(n):
        if n not in memo:
            memo[n] = set()
            for s in succ[n]:
                memo[n] |= {s} | reach(s)
        return memo[n]
    return reach


def static_coverage(fixture, label):
    """A covered activity c with positive duration is impossible if c precedes the start-event activity
    (c finishes before the interval opens) or the release activity precedes c (c starts after release)."""
    edges = [(d["predecessor"], d["successor"]) for d in fixture["dependencies"]]
    reach = closure(edges)
    dur = {a["id"]: a["duration_minutes"] for a in fixture["activities"]}
    rows = []
    for rv in fixture["reservations"]:
        start = rv["start_event"]["activity_id"]
        release = [x["activity_id"] for x in rv["release_condition"]["all_of"]]
        for c in rv["covers_activities"]:
            before_open = c != start and start in reach(c) and dur[c] > 0
            after_release = any(c != r and c in reach(r) for r in release) and dur[c] > 0
            implied_inside = (c == start or c in reach(start)) and all(c == r or r in reach(c) for r in release)
            status = ("CONTRADICTION: finishes before reservation opens" if before_open else
                      "CONTRADICTION: starts after release" if after_release else
                      "implied by precedence" if implied_inside else "needs schedule check")
            rows.append({"fixture": label, "reservation_id": rv["reservation_id"], "resource_id": rv["resource_id"],
                         "start_event": f"{start}.start", "release": "+".join(f"{r}.finish" for r in release),
                         "covered_activity": c, "static_status": status})
    return rows


# --------------------------------------------------------------------------- coverage-aware checker
def check_with_coverage(fixture, sched):
    rows, _ = b.check_schedule(fixture, sched)  # calendars, durations, precedence, strike, capacity incl. reservations
    start = {k: b.epoch_min(v[0][:16]) for k, v in sched.items()}
    finish = {k: b.epoch_min(v[1][:16]) for k, v in sched.items()}
    for rv in fixture["reservations"]:
        lo = start[rv["start_event"]["activity_id"]]
        hi = max(finish[x["activity_id"]] for x in rv["release_condition"]["all_of"]) + \
            rv["release_condition"]["return_lead_minutes"]
        for c in rv["covers_activities"]:
            ok = lo <= start[c] and finish[c] <= hi
            rows.append({"check": "reservation_covers_activity (V8)", "subject": f"{rv['reservation_id']}:{c}",
                         "passed": ok, "detail": "" if ok else
                         f"{c} {sched[c][0]}..{sched[c][1]} outside {b.stamp((lo - b.ANCHOR) // b.TICK)}.."
                         f"{b.stamp((hi - b.ANCHOR) // b.TICK)}"})
    return rows


def schedule_from_csv(path):
    with path.open(encoding="utf-8-sig") as f:
        return {r["activity_id"]: (r["start"], r["finish"]) for r in csv.DictReader(f)}


# --------------------------------------------------------------------------- recompute from JSON alone
def recompute(fixture):
    """Run the independent engine on the JSON content only (constants are asserted equal, not assumed)."""
    cal = {c["calendar_id"]: c for c in fixture["calendars"]}
    exceptions = cal["PROJECT"]["date_exceptions"]
    assert all(c["date_exceptions"] == exceptions for c in cal.values())
    for cid, spec in b.CALENDARS.items():
        assert {(w["start"], w["end"]) for w in cal[cid]["working_windows"]} == set(spec["windows"]), cid
    for r in fixture["resources"]:
        v = b.RESOURCES[r["resource_id"]]
        assert (r["resource_class"], r["unit"], r["capacity"], r["availability"], r["calendar_ref"], r["explicit_none"]) \
            == (v[0], v[1], v[2], v[3], v[4], v[5]), r["resource_id"]
    b.DATE_EXCEPTIONS = list(exceptions)
    model = b.Model(fixture["activities"], fixture["dependencies"], fixture["reservations"])
    cpm = model.cpm()
    lb, stats = b.lower_bound(model)
    best = None
    for seed in range(1200):
        rng = b.random.Random(seed) if seed else None
        rule = "earliest" if seed % 2 == 0 else "latest_start"
        out = b.sgs(model, lb["cpm"]["ls"], rng, noise=0 if seed < 2 else (60 if seed < 600 else 600), rule=rule)
        if out and (best is None or out["span"] < best["span"]):
            best = out
    sched = {a: (b.stamp(best["es"][a]), b.stamp(best["ef"][a])) for a in model.ids}
    cpm_sched = {a: (b.stamp(cpm["es"][a]), b.stamp(cpm["ef"][a])) for a in model.ids}
    _, conflicts = b.check_schedule(fixture, cpm_sched)
    return {"model": model, "cpm": cpm, "best": best, "lb": lb, "lb_stats": stats, "sched": sched,
            "cpm_conflicts": conflicts, "cost": round(sum(a["cost_eur"] for a in fixture["activities"]), 6)}


def diff(a, c, path=""):
    out = []
    if isinstance(a, dict) and isinstance(c, dict):
        for k in sorted(set(a) | set(c)):
            if k not in a or k not in c:
                out.append((f"{path}/{k}", a.get(k, "<absent>"), c.get(k, "<absent>")))
            else:
                out += diff(a[k], c[k], f"{path}/{k}")
    elif isinstance(a, list) and isinstance(c, list) and len(a) == len(c) and all(isinstance(x, (dict, list)) for x in a):
        for i, (x, y) in enumerate(zip(a, c)):
            out += diff(x, y, f"{path}[{i}]")
    elif a != c:
        out.append((path, a, c))
    return out


def main():
    manifest7 = {e["path"]: e["sha256"] for e in load(PKG / "deliverable_manifest.json")["files"]}
    sources = {"original": DEMO / "fixture_inputs.json", "holiday": HOL / "fixture_inputs.json"}
    schedules = {"original": DEMO / "resource_feasible_schedule.csv", "holiday": HOL / "resource_feasible_schedule.csv"}
    originals = {k: load(p) for k, p in sources.items()}
    preserved = {k: {"path": p.relative_to(PKG).as_posix(), "sha256": sha(p),
                     "matches_task7_manifest": sha(p) == manifest7[p.relative_to(PKG).as_posix()]}
                 for k, p in {**sources, **{f"{k}_schedule": p for k, p in schedules.items()}}.items()}

    # 1-2. static analysis of every reservation in every reference file that declares coverage
    coverage = []
    for k, fx in originals.items():
        coverage += static_coverage(fx, f"{k} (historical v1.0)")
    other_files = {}
    for p in sorted(PKG.rglob("*.json")):
        if "corrections" in p.parts:
            continue
        text = p.read_text(encoding="utf-8-sig")
        other_files[p.relative_to(PKG).as_posix()] = {"mentions_reservations": "reservation" in text,
                                                      "declares_covers_activities": "covers_activities" in text}
    t4 = load(PKG / "cpsat_reference_cases.json")
    rc05 = [{"case": c["case_id"], "reservation": r["id"], "from": r["from_activity"], "to": r["to_activity"],
             "covers_activities": r.get("covers_activities", "not declared")}
            for c in t4["cases"] for r in c.get("reservations", [])]

    # 3. corrected v1.1 fixtures
    corrected, diffs = {}, {}
    for k, fx in originals.items():
        c = copy.deepcopy(fx)
        removed = {}
        for rv in c["reservations"]:
            if rv["reservation_id"] in COLUMN_RES:
                col = rv["reservation_id"].split("-")[-1]
                assert rv["start_event"]["activity_id"] == f"{col}-FORM"
                rv["covers_activities"] = [a for a in rv["covers_activities"] if a != f"{col}-REBAR"]
                removed[rv["reservation_id"]] = f"{col}-REBAR"
        c["_meta"]["correction"] = {
            "id": "C01", "fixture_version": VERSION, "supersedes_sha256": preserved[k]["sha256"],
            "supersedes_path": preserved[k]["path"],
            "change": "Removed the cage-first REBAR activity from the covers_activities of R-COLSET-C1..C4 only.",
            "removed": removed,
            "rationale": "Columns are cage-first (AP-DR05 rule C-REBAR -> C-FORM). The cage is fixed before the column "
                         "formwork set is erected, so REBAR neither occupies the set nor can lie inside a reservation "
                         "that opens at FORM start. Beams and slabs are formwork-first; their REBAR stays covered.",
            "status": "Reference correction only. Not an engineering approval; AP-X-FW-03 remains PENDING."}
        corrected[k] = c
        d = [(p, a, x) for p, a, x in diff(fx, c) if not p.startswith("/_meta/correction")]
        diffs[k] = [{"path": p, "before": a, "after": x} for p, a, x in d]
        assert len(d) == 4 and all("covers_activities" in p for p, _, _ in d), d
        assert all(len(a) - len(x) == 1 and set(a) - set(x) == {next(v for v in removed.values() if v in a)}
                   for _, a, x in d), d
        write_json(COR / k / f"fixture_inputs_{VERSION}.json", c)

    # 4. checker: originals rejected (static + committed schedules), corrected accepted
    checks = []
    for k in originals:
        hist = schedule_from_csv(schedules[k])
        for label, fx in (("historical v1.0", originals[k]), (f"corrected {VERSION}", corrected[k])):
            rows = check_with_coverage(fx, hist)
            fails = [r for r in rows if not r["passed"]]
            static_bad = [r for r in static_coverage(fx, label) if r["static_status"].startswith("CONTRADICTION")]
            checks.append({"fixture": k, "fixture_version": label, "schedule": "historical committed schedule",
                           "checks": len(rows), "failed": len(fails),
                           "failed_subjects": " ".join(r["subject"] for r in fails),
                           "static_contradictions": len(static_bad),
                           "verdict": "REJECTED" if fails or static_bad else "ACCEPTED"})

    # 5. independent recomputation from corrected JSON
    results = {}
    for k, fx in corrected.items():
        r = recompute(fx)
        rows = check_with_coverage(fx, r["sched"])
        fails = [x for x in rows if not x["passed"]]
        proven = r["best"]["span"] == r["lb"]["value"]
        results[k] = {
            "fixture": f"{k}/fixture_inputs_{VERSION}.json", "fixture_sha256": sha(COR / k / f"fixture_inputs_{VERSION}.json"),
            "status": "OPTIMAL (proven: equals lower bound)" if proven else "FEASIBLE (optimality not proven)",
            "makespan_minutes": r["best"]["span"] * b.TICK, "completion_local": b.stamp(r["best"]["span"]),
            "lower_bound_minutes": r["lb"]["value"] * b.TICK, "lower_bound_completion": b.stamp(r["lb"]["value"]),
            "cpm_makespan_minutes": r["cpm"]["span"] * b.TICK, "cpm_completion_local": b.stamp(r["cpm"]["span"]),
            "cpm_conflict_intervals": len(r["cpm_conflicts"]),
            "cpm_over_capacity_pools": sorted({c["resource"] for c in r["cpm_conflicts"]}),
            "direct_reference_cost_eur": r["cost"], "checks": len(rows), "checks_failed": len(fails),
            "coverage_checks": sum(1 for x in rows if x["check"].startswith("reservation_covers")),
            "lower_bound_choices": r["lb_stats"]}
        write_csv(COR / k / f"resource_feasible_schedule_{VERSION}.csv",
                  [{"activity_id": a, "start": s, "finish": f} for a, (s, f) in sorted(r["sched"].items(), key=lambda x: (x[1][0], x[0]))])
        write_csv(COR / k / f"feasibility_checks_{VERSION}.csv", rows)
        write_json(COR / k / f"expected_results_{VERSION}.json", results[k])

    # 6. invariants beyond the diff: capacities, durations, dependencies, calendars, costs, quantities
    invariants = {}
    for k in originals:
        o, c = originals[k], corrected[k]
        invariants[k] = {name: o[name] == c[name] for name in
                         ("resources", "crew_modes", "calendars", "activities", "dependencies", "elements", "supports",
                          "work_packages", "supply", "holds", "split_policy", "project")}
        invariants[k]["reservations_except_column_covers"] = [
            {kk: vv for kk, vv in r.items() if not (r["reservation_id"] in COLUMN_RES and kk == "covers_activities")}
            for r in o["reservations"]] == [
            {kk: vv for kk, vv in r.items() if not (r["reservation_id"] in COLUMN_RES and kk == "covers_activities")}
            for r in c["reservations"]]

    write_csv(COR / "coverage_analysis.csv", coverage)
    write_csv(COR / "checker_results.csv", checks)
    write_json(COR / "fixture_diff.json", {"diff_excluding_correction_block": diffs, "invariants_equal": invariants,
                                           "other_reference_files": other_files, "task4_rc05_reservations": rc05})
    write_json(COR / "correction_manifest.json", {
        "correction": "C01", "fixture_version": VERSION,
        "historical_preserved": preserved,
        "corrected": {k: {"path": f"corrections/C01_column_reservation_coverage/{k}/fixture_inputs_{VERSION}.json",
                          "sha256": results[k]["fixture_sha256"], "supersedes": preserved[k]["path"]} for k in corrected},
        "benchmark_inputs_for_acceptance": {k: f"corrections/C01_column_reservation_coverage/{k}/fixture_inputs_{VERSION}.json"
                                            for k in corrected},
        "files": {p.relative_to(COR).as_posix(): sha(p) for p in sorted(COR.rglob("*"))
                  if p.is_file() and p.name not in ("correction_manifest.json",) and "__pycache__" not in p.parts}})
    print(json.dumps({"preserved": preserved, "checks": checks, "results": results, "invariants": invariants,
                      "contradictions": [r for r in coverage if r["static_status"].startswith("CONTRADICTION")],
                      "diff": diffs, "rc05": rc05}, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
