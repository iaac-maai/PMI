"""Independent F01 regression checker (split-pour supply reporting).

It reads optimizer RESULT JSON files only. It does not import or run production code, so it is unaffected
by the pmi_core/optimization relocation. Every expected figure is recomputed from the returned segment
timestamps and the scenario file; reported fields are located through a field map.

Usage once a stable integrated commit exists:
  1. Build the variant inputs:   python check_f01.py --write-inputs OUT_DIR
  2. Run the integrated CLI on OUT_DIR/f01_A_restart_30.json and OUT_DIR/f01_B_restart_0.json
     (normalized --input path) and save each JSON result.
  3. Check:  python check_f01.py --result-a A.json --result-b B.json [--field-map MAP.json]
Self-test (no optimizer):  python check_f01.py --self-test
"""

import argparse
import copy
import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCENARIO = json.loads((HERE / "f01_scenarios.json").read_text(encoding="utf-8"))
RATE = 6           # m3/h drawn by S (scenario)
POUR = "S"
UNIT_PRICE = 118.57
FORBIDDEN_COST = round(63 * UNIT_PRICE, 2)   # 7469.91: allowance-inflated material cost
MEASURED = re.compile(r"measur|consum|actual|as[_-]?built|exact|metered|delivered_actual", re.I)


def variant_problem(name):
    p = copy.deepcopy(SCENARIO["base_problem"])
    overhead = SCENARIO["variants"][name]["activities.S.split.restart_overhead_minutes"]
    next(a for a in p["activities"] if a["id"] == POUR)["split"]["restart_overhead_minutes"] = overhead
    return p, overhead


def minutes(a, b):
    return int((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() // 60)


def walk(obj, path=""):
    """Yield (path, key, value) for every scalar in a nested JSON value."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, f"{path}.{k}" if path else k)
            if not isinstance(v, (dict, list)):
                yield f"{path}.{k}" if path else k, k, v
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")


def as_number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            if "/" in v:
                n, d = v.split("/")
                return float(n) / float(d)
            return float(v)
        except ValueError:
            return None
    return None


def total_of(result, key):
    """Sum every numeric value reported under a field name (per-day rows are summed)."""
    vals = [as_number(v) for _, k, v in walk(result) if k == key]
    vals = [v for v in vals if v is not None]
    return (sum(vals), len(vals)) if vals else (None, 0)


def check(result, name, field_map):
    expected = SCENARIO["expected"][name]
    _, overhead = variant_problem(name)
    rows = []

    def add(cid, ok, detail):
        rows.append({"variant": name, "check": cid, "passed": bool(ok), "detail": detail})

    add("F01-0 status", result.get("status") == "OPTIMAL" and result.get("validated") is True,
        f"status={result.get('status')} validated={result.get('validated')}")
    act = next((a for a in result.get("activities", []) if a.get("id") == POUR), None)
    if act is None:
        add("F01-1 pour scheduled", False, "S missing")
        return rows
    segs = act["segments"]
    seg_min = [minutes(a, b) for a, b in segs]
    restarts = max(0, len(segs) - 1)
    productive = sum(seg_min) - overhead * restarts
    placed = RATE * productive / 60
    allowance = RATE * overhead * restarts / 60
    add("F01-1 segments", segs == expected["segments_S"], f"{segs}")
    add("F01-2 productive minutes", productive == expected["productive_minutes_S"], f"{productive}")
    add("F01-3 independent volumes", (placed, allowance, placed + allowance) ==
        (expected["planned_placed_volume_m3"], expected["restart_allowance_m3"], expected["total_supply_allowance_m3"]),
        f"placed={placed} allowance={allowance} total={placed + allowance}")
    add("F01-4 makespan", result.get("objective_minutes") == expected["makespan_minutes"], f"{result.get('objective_minutes')}")

    rep_placed, n1 = total_of(result, field_map["placed_volume"])
    rep_allow, n2 = total_of(result, field_map["restart_allowance"])
    rep_total, n3 = total_of(result, field_map["total_allowance"])
    add("F01-5 placed volume reported", n1 > 0 and abs(rep_placed - placed) < 1e-9,
        f"{field_map['placed_volume']}={rep_placed} (expected {placed})")
    add("F01-6 restart allowance reported separately", n2 > 0 and abs(rep_allow - allowance) < 1e-9,
        f"{field_map['restart_allowance']}={rep_allow} (expected {allowance})")
    add("F01-7 total labelled as allowance", n3 == 0 or abs(rep_total - (placed + allowance)) < 1e-9,
        f"{field_map['total_allowance']}={rep_total} (optional; must equal {placed + allowance})")
    # No measurement-like field may carry the allowance-inclusive total or the allowance.
    # Values that include the allowance: the overall total and every day total that contains a restart.
    with_allowance = {placed + allowance}
    if overhead:
        with_allowance |= {v["total_m3"] for v in expected.get("daily", {}).values() if v["restart_allowance_m3"]}
    offenders = [(p, v) for p, k, v in walk(result)
                 if overhead and MEASURED.search(k) and "m3" in k.lower() and as_number(v) is not None
                 and any(abs(as_number(v) - w) < 1e-9 for w in with_allowance)]
    add("F01-8 no measurement-labelled allowance", not offenders, f"offending fields: {offenders[:4]}")
    states = [v for p, k, v in walk(result) if k == "input_state" and "supply" in p.lower()]
    add("F01-9 not marked as measured", "independently_measured" not in states, f"supply input_states {sorted(set(states))}")
    occ = [r for r in result.get("resource_occupancy", []) if r.get("resource_id") == "SUPPLY"]
    restart_rows = [r for r in occ if any(t in str(r.get("occupancy_basis", "")) for t in field_map["occupancy_basis_for_restart"])]
    add("F01-10 restart occupancy labelled", (not overhead) or bool(restart_rows),
        f"SUPPLY occupancy bases {sorted({r.get('occupancy_basis') for r in occ})}")
    cost = (result.get("cost") or {}).get("total_direct_reference_eur")
    act_cost = act.get("reference_cost_eur")
    costs = [as_number(v) for _, k, v in walk(result) if "cost" in k.lower() and as_number(v) is not None]
    add("F01-11 cost unchanged by allowance", cost == expected["direct_reference_cost_eur"] == act_cost
        and all(abs(c - FORBIDDEN_COST) > 0.005 for c in costs), f"total={cost} S={act_cost}")
    return rows


def compare(a, b):
    ca = (a.get("cost") or {}).get("total_direct_reference_eur")
    cb = (b.get("cost") or {}).get("total_direct_reference_eur")
    return [{"variant": "A vs B", "check": "F01-12 cost identical with and without restart overhead",
             "passed": ca == cb == SCENARIO["expected"]["A_restart_30"]["direct_reference_cost_eur"],
             "detail": f"A={ca} B={cb}"}]


def run(a, b, field_map):
    rows = check(a, "A_restart_30", field_map) + check(b, "B_restart_0", field_map) + compare(a, b)
    return rows, all(r["passed"] for r in rows)


def synthetic(overhead, *, fixed=True, inflate=False):
    """A hand-built result shaped like the d72eda3 output, for the checker's self-test only."""
    exp = SCENARIO["expected"]["A_restart_30" if overhead else "B_restart_0"]
    segs = exp["segments_S"]
    placed, allowance = 60, 6 * overhead / 60
    supply = [{"resource_id": "SUPPLY", "date": "2027-01-15", "draw_m3_exact": "24"},
              {"resource_id": "SUPPLY", "date": "2027-01-18", "draw_m3_exact": str(36 + allowance)}]
    if fixed:
        supply = [{"resource_id": "SUPPLY", "date": "2027-01-15", "placed_volume_m3": 24, "restart_allowance_m3": 0,
                   "supply_allowance_m3": 24},
                  {"resource_id": "SUPPLY", "date": "2027-01-18", "placed_volume_m3": 36, "restart_allowance_m3": allowance,
                   "supply_allowance_m3": 36 + allowance}]
    occupancy = [{"resource_id": "SUPPLY", "holder_id": "S", "occupancy_basis": "working_time",
                  "start": segs[0][0], "finish": segs[0][1]}]
    if overhead:
        occupancy.append({"resource_id": "SUPPLY", "holder_id": "S",
                          "occupancy_basis": "restart_allowance" if fixed else "working_time",
                          "start": segs[1][0], "finish": "2027-01-18T08:30+01:00"})
    cost = 7469.91 if inflate else 7114.2
    return {"status": "OPTIMAL", "validated": True, "objective_minutes": exp["makespan_minutes"],
            "activities": [{"id": "PREP", "segments": [["2027-01-15T08:00+01:00", "2027-01-15T12:00+01:00"]]},
                           {"id": "S", "segments": segs, "reference_cost_eur": cost}],
            "supply_checks": supply, "resource_occupancy": occupancy, "cost": {"total_direct_reference_eur": cost}}


def self_test(field_map):
    good, ok_good = run(synthetic(30), synthetic(0), field_map)
    current, ok_current = run(synthetic(30, fixed=False), synthetic(0, fixed=False), field_map)
    inflated, ok_infl = run(synthetic(30, inflate=True), synthetic(0), field_map)
    failed_current = sorted({r["check"] for r in current if not r["passed"]})
    failed_infl = sorted({r["check"] for r in inflated if not r["passed"]})
    result = {"corrected_shape_passes": ok_good, "d72eda3_shape_rejected": not ok_current,
              "d72eda3_shape_failed_checks": failed_current, "inflated_cost_rejected": not ok_infl,
              "inflated_failed_checks": failed_infl}
    result["self_test_pass"] = ok_good and not ok_current and not ok_infl and \
        "F01-6 restart allowance reported separately" in failed_current and "F01-11 cost unchanged by allowance" in failed_infl
    return result, good


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--write-inputs", type=Path)
    ap.add_argument("--result-a", type=Path)
    ap.add_argument("--result-b", type=Path)
    ap.add_argument("--field-map", type=Path)
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()
    field_map = SCENARIO["default_field_map"] | (json.loads(args.field_map.read_text()) if args.field_map else {})
    if args.write_inputs:
        args.write_inputs.mkdir(parents=True, exist_ok=True)
        for name in SCENARIO["variants"]:
            p, _ = variant_problem(name)
            (args.write_inputs / f"f01_{name}.json").write_text(json.dumps(p, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {len(SCENARIO['variants'])} inputs to {args.write_inputs}")
        return 0
    if args.self_test:
        summary, rows = self_test(field_map)
        print(json.dumps(summary, indent=2))
        if args.report:
            args.report.write_text(json.dumps({"self_test": summary, "corrected_shape_rows": rows}, indent=2) + "\n", encoding="utf-8")
        return 0 if summary["self_test_pass"] else 1
    a = json.loads(args.result_a.read_text(encoding="utf-8"))
    b = json.loads(args.result_b.read_text(encoding="utf-8"))
    rows, ok = run(a, b, field_map)
    for r in rows:
        print(("PASS " if r["passed"] else "FAIL ") + r["variant"] + " " + r["check"] + " | " + r["detail"])
    if args.report:
        args.report.write_text(json.dumps({"passed": ok, "rows": rows}, indent=2) + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
