"""Correction C02: add the R2-3 acceptance_criterion_ref to Task 7 RC13b as versioned metadata (case v1.1).

Reads task7_reference_cases.json (never writes it). Writes RC13b_v1.1.json, verifies that the only change is
the added field, and recomputes the expected projection with the independent Task 4 engine to show it is
unchanged (status CONDITIONAL, 5,880 min, same POUR/STRIP dates).
"""

import copy
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
COR = HERE.parent
PKG = HERE.parents[2]
sys.path.insert(0, str(PKG / "scripts"))
import build_task7_cases as t7  # noqa: E402  (Task 4 engine with R2 default policy)

REF = "HYP-RC13B-PLANNED-STRENGTH-TEST-CRITERION"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def diff(a, b, path=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append((f"{path}/{k}", a.get(k, "<absent>"), b.get(k, "<absent>")))
            else:
                out += diff(a[k], b[k], f"{path}/{k}")
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, f"{path}[{i}]")
    elif a != b:
        out.append((path, a, b))
    return out


def main():
    src = PKG / "task7_reference_cases.json"
    doc = json.loads(src.read_text(encoding="utf-8"))
    original = next(c for c in doc["cases"] if c["case_id"] == "RC13b")
    corrected = copy.deepcopy(original)
    event = corrected["strength_events"][0]
    assert "acceptance_criterion_ref" not in event
    event["acceptance_criterion_ref"] = REF
    corrected["case_version"] = "v1.1"
    corrected["correction"] = {
        "id": "C02", "supersedes": "task7_reference_cases.json#RC13b (v1.0)", "supersedes_file_sha256": sha(src),
        "change": "Added strength_events[0].acceptance_criterion_ref, required by R2-3 for planned or pending tests.",
        "criterion_ref_meaning": ("Identifier of a HYPOTHETICAL planned-test acceptance criterion. It names the criterion "
                                  "slot only; it states no strength value, test method or striking threshold. The "
                                  "criterion itself remains for engineering decision under AP-X-STR-02 (PENDING)."),
        "unchanged": "Construction assumptions, durations, dependencies, resources, the 96 h test age, status semantics "
                     "and the expected outcome."}
    changes = [(p, a, b) for p, a, b in diff(original, corrected) if not p.startswith(("/correction", "/case_version"))]
    assert changes == [("/strength_events[0]/acceptance_criterion_ref", "<absent>", REF)], changes

    # Recompute the projection independently; the engine ignores event metadata by design.
    recomputed = t7.t4.solve_case({k: v for k, v in corrected.items() if k not in ("expected", "correction", "case_version")})
    sched = {r["id"]: (r["start"], r["finish"]) for r in recomputed["reference_schedule"]}
    exp = original["expected"]
    exp_sched = {r["id"]: (r["start"], r["finish"]) for r in exp["schedule"]}
    unchanged = (recomputed["optimal_makespan_minutes"] == exp["optimal_makespan_minutes"] == 5880
                 and sched == exp_sched and exp["expected_status"] == "CONDITIONAL")
    assert unchanged, (recomputed["optimal_makespan_minutes"], sched, exp_sched)

    (COR / "RC13b_v1.1.json").write_text(json.dumps(corrected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report = {"correction": "C02", "case": "RC13b", "case_version": "v1.1",
              "source": {"path": "task7_reference_cases.json", "sha256": sha(src), "modified": False},
              "corrected_case": {"path": "corrections/C02_rc13b_acceptance_criterion_ref/RC13b_v1.1.json",
                                 "sha256": sha(COR / "RC13b_v1.1.json")},
              "diff_excluding_correction_block": [{"path": p, "before": a, "after": b} for p, a, b in changes],
              "expected_outcome_unchanged": unchanged,
              "independent_recomputation": {"projection_makespan_minutes": recomputed["optimal_makespan_minutes"],
                                            "schedule": sched, "expected_status_semantics": "CONDITIONAL (R2-3 planned test)"}}
    (COR / "c02_verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
