"""Independent F01 closure run against the relocated optimizer (normal normalized-input CLI path).

Inputs: the prepared, unchanged F01 scenario files. The declared-plan variants add only three documented
fields to S (planned_placed_volume_m3 = 60, placement_profile = declared_constant_rate, evidence_ref): the
physical plan must be declared, because the contract forbids inferring it from the allowance. The
unchanged inputs are run as the "evidence absent" case, where the plan must stay unknown (null).
"""

import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
REPO = HERE.parents[4]
PREP = REPO / "research/validation/stage5_4b_independent/integration_prep/F01_split_pour_supply"
PY = sys.executable
FIELD_MAP = {"placed_volume": "aggregate_planned_placed_volume_m3",
             "restart_allowance": "aggregate_restart_capacity_allowance_m3",
             "total_allowance": "aggregate_total_capacity_allowance_m3",
             "occupancy_basis_for_restart": ["restart_capacity_allowance"]}
DECLARATION = {"planned_placed_volume_m3": 60, "placement_profile": "declared_constant_rate",
               "evidence_ref": "F01 declared physical plan (hypothetical): 60 m3 at constant placement rate"}
LEVEL_KEYS = ("planned_placed_volume_m3", "productive_capacity_allowance_m3",
              "restart_capacity_allowance_m3", "total_capacity_allowance_m3")
FORBIDDEN_WORDS = ("measured", "consumed", "consumption", "actual", "as_built", "co2", "carbon",
                   "embodied", "environment", "material_quantity", "material_cost")


def run_cli(problem, tag):
    path = OUT / "f01_runs" / f"{tag}_input.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(problem, indent=2) + "\n", encoding="utf-8")
    proc = subprocess.run([PY, "-B", "-m", "research.implementation.stage5_4b", "--input", str(path)],
                          cwd=REPO, capture_output=True, text=True)
    (OUT / "f01_runs" / f"{tag}_result.json").write_text(proc.stdout, encoding="utf-8")
    return json.loads(proc.stdout), proc.returncode


def frac(v):
    return None if v is None else Fraction(v)


def walk(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else k
            yield p, k, v
            yield from walk(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")


def level_checks(result, *, declared, overhead):
    rows = []

    def add(cid, ok, detail):
        rows.append({"check": cid, "passed": bool(ok), "detail": detail})
    allowance = Fraction(6 * overhead, 60)
    want_planned = Fraction(60) if declared else None
    act = next(r for r in result["supply_by_activity"] if r["activity_id"] == "S")
    src = result["supply_by_source"][0]
    tot = result["supply_totals"]
    for label, row, prefix in (("activity", act, ""), ("source", src, ""), ("aggregate", tot, "aggregate_")):
        got = tuple(frac(row[prefix + k]) for k in LEVEL_KEYS)
        want = (want_planned, Fraction(60), allowance, 60 + allowance)
        add(f"L-{label}", got == want, f"{label}: {[str(x) for x in got]} expected {[str(x) for x in want]}")
    days = {r["date"]: r for r in result["supply_checks"]}
    fri, mon = days["2027-01-15"], days["2027-01-18"]
    want_fri = (Fraction(24) if declared else None, Fraction(24), Fraction(0), Fraction(24))
    want_mon = (Fraction(36) if declared else None, Fraction(36), allowance, 36 + allowance)
    add("L-daily Fri", tuple(frac(fri[k]) for k in LEVEL_KEYS) == want_fri, json.dumps({k: fri[k] for k in LEVEL_KEYS}))
    add("L-daily Mon", tuple(frac(mon[k]) for k in LEVEL_KEYS) == want_mon, json.dumps({k: mon[k] for k in LEVEL_KEYS}))
    others = [r for d, r in days.items() if d not in ("2027-01-15", "2027-01-18")]
    add("L-daily other days zero", all(frac(r["total_capacity_allowance_m3"]) == 0 for r in others), f"{len(others)} days")
    occ = [r for r in result["resource_occupancy"] if r["resource_id"] == "SUPPLY"]
    restart = [r for r in occ if r["occupancy_basis"] == "restart_capacity_allowance"]
    expected_restart = [("2027-01-18T08:00+01:00", "2027-01-18T08:30+01:00")] if overhead else []
    add("L-occupancy labels", [(r["start"], r["finish"]) for r in restart] == expected_restart
        and {r["occupancy_basis"] for r in occ} <= {"productive_capacity_allowance", "restart_capacity_allowance"},
        f"{[(r['occupancy_basis'], r['start'], r['finish']) for r in occ]}")
    s = next(a for a in result["activities"] if a["id"] == "S")
    add("L-engineering quantity untouched", s.get("planned_placed_volume_m3") == (60 if declared else None)
        and s.get("reference_cost_eur") == 7114.2, f"S planned={s.get('planned_placed_volume_m3')} cost={s.get('reference_cost_eur')}")
    add("L-cost unchanged", result["cost"]["total_direct_reference_eur"] == 7114.2, f"{result['cost']}")
    bad = [p for p, k, v in walk(result) if any(w in k.lower() for w in FORBIDDEN_WORDS)
           and not isinstance(v, (dict, list))]
    add("L-no measured/actual/material/environment fields", not bad, f"{bad[:5]}")
    add("L-supply input_state not measured", all(
        v != "independently_measured" for p, k, v in walk(result) if k == "input_state" and "SUPPLY" in p),
        "supply provenance")
    return rows


def main():
    sys.path.insert(0, str(PREP))
    import check_f01 as chk  # the prepared, unchanged independent checker
    inputs = {n: json.loads((PREP / "inputs" / f"f01_{n}.json").read_text(encoding="utf-8")) for n in ("A_restart_30", "B_restart_0")}
    results, codes = {}, {}
    for name, base in inputs.items():
        declared = json.loads(json.dumps(base))
        next(a for a in declared["activities"] if a["id"] == "S").update(DECLARATION)
        results[f"{name}_declared"], codes[f"{name}_declared"] = run_cli(declared, f"{name}_declared")
        results[f"{name}_unchanged"], codes[f"{name}_unchanged"] = run_cli(base, f"{name}_unchanged")
    prepared_rows, prepared_ok = chk.run(results["A_restart_30_declared"], results["B_restart_0_declared"],
                                         chk.SCENARIO["default_field_map"] | FIELD_MAP)
    unknown_rows, _ = chk.run(results["A_restart_30_unchanged"], results["B_restart_0_unchanged"],
                              chk.SCENARIO["default_field_map"] | FIELD_MAP)
    unknown_expected_fail = sorted({r["check"] for r in unknown_rows if not r["passed"]})
    levels = {}
    for name, overhead in (("A_restart_30", 30), ("B_restart_0", 0)):
        for mode in ("declared", "unchanged"):
            levels[f"{name}_{mode}"] = level_checks(results[f"{name}_{mode}"], declared=mode == "declared", overhead=overhead)
    summary = {name: {"status": r["status"], "validated": r["validated"], "exit_code": codes[name],
                      "makespan": r["objective_minutes"], "project_makespan": r.get("project_makespan_minutes"),
                      "schedule_scope": r.get("schedule_scope"), "supply_totals": r.get("supply_totals"),
                      "cost": r["cost"]["total_direct_reference_eur"]} for name, r in results.items()}
    level_ok = all(row["passed"] for rows in levels.values() for row in rows)
    unknown_ok = unknown_expected_fail == ["F01-5 placed volume reported"]
    makespans = (results["A_restart_30_declared"]["objective_minutes"], results["B_restart_0_declared"]["objective_minutes"])
    closed = prepared_ok and level_ok and unknown_ok and makespans == (4710, 4680)
    out = {"decision": "F01 CLOSED" if closed else "F01 NOT CLOSED",
           "path": "research CLI --input (delegates to pmi_core.optimization.solve with the trusted registry)",
           "field_map": FIELD_MAP, "declaration_added_for_declared_variants": DECLARATION,
           "prepared_checker_declared": {"passed": prepared_ok, "rows": prepared_rows},
           "prepared_checker_evidence_absent": {"failed_checks": unknown_expected_fail,
                                                "interpretation": "Only F01-5 fails, as required: the plan stays unknown (null) when no physical evidence is declared."},
           "level_checks": levels, "level_checks_passed": level_ok, "summary": summary}
    (OUT / "f01_independent_result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"decision": out["decision"], "prepared_ok": prepared_ok, "level_ok": level_ok,
                      "unknown_failed": unknown_expected_fail, "summary": summary}, indent=1))
    for k, rows in levels.items():
        for r in rows:
            if not r["passed"]:
                print("LEVEL FAIL", k, r)


if __name__ == "__main__":
    main()
