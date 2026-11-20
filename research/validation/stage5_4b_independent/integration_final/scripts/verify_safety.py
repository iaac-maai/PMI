"""Architecture, authority and output-safety probes for Stage 5.4B.3 (planning interpreter, repo root)."""

import ast
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
REPO = HERE.parents[4]
sys.path.insert(0, str(REPO))
PKG = REPO / "research/validation/stage5_4a_independent_verification"

import pmi_core.optimization as opt  # noqa: E402
import pmi_core.optimization.engine as opt_engine  # noqa: E402
from pmi_core.optimization.capacity_dates import capacity_periods  # noqa: E402
from pmi_core.optimization.registry import ControlledRegistry  # noqa: E402
from pmi_core.schedule_result import schedule_result  # noqa: E402
import research.implementation.stage5_4b.engine as research_engine  # noqa: E402
from research.implementation.stage5_4b.fixtures import approvals, frozen_r0, normalize_reference, reference_cases  # noqa: E402
from research.implementation.stage5_4b.demo import construction_demo  # noqa: E402


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def imports(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add(("." * node.level) + (node.module or ""))
    return names


def main():
    res = {}
    # --- architecture
    core_files = sorted((REPO / "pmi_core/optimization").glob("*.py")) + [REPO / "pmi_core/application.py", REPO / "pmi_core/schedule_result.py"]
    research_imports = {p.relative_to(REPO).as_posix(): sorted(i for i in imports(p) if i.startswith("research") or "fixtures" in i)
                        for p in core_files}
    res["no_research_imports_in_pmi_core_optimization_application"] = not any(research_imports.values())
    app_text = (REPO / "pmi_core/application.py").read_text(encoding="utf-8")
    res["application_has_no_research_or_fixture_paths"] = "research" not in app_text and "fixture" not in app_text.lower()
    cp_users = sorted(p.relative_to(REPO).as_posix() for p in REPO.rglob("*.py")
                      if not any(part.startswith(".venv") for part in p.parts) and "__pycache__" not in p.parts
                      and "validation" not in p.parts
                      and ("CpModel(" in p.read_text(encoding="utf-8", errors="ignore") or "add_cumulative" in p.read_text(encoding="utf-8", errors="ignore")))
    res["cp_sat_model_builders"] = cp_users
    res["single_optimizer_implementation"] = cp_users == ["pmi_core/optimization/model.py"] or all(p.startswith("pmi_core/optimization/") for p in cp_users)
    research_dir = REPO / "research/implementation/stage5_4b"
    wrappers = {p.name: len(p.read_text(encoding="utf-8").splitlines()) for p in research_dir.glob("*.py")
                if p.name in ("engine.py", "advanced.py", "capacity_dates.py", "input_states.py")}
    res["research_wrappers_line_counts"] = wrappers
    # delegation: patch the relocated solve and call the research CLI's solve
    sentinel = object()
    original = opt_engine.solve
    opt_engine.solve = lambda problem, **kw: (sentinel, kw.get("registry"))
    try:
        got, reg = research_engine.solve({"x": 1})
    finally:
        opt_engine.solve = original
    res["research_solve_delegates_to_pmi_core_optimization"] = got is sentinel and isinstance(reg, ControlledRegistry)
    # --- authority
    rc01 = normalize_reference(reference_cases()["RC01"])
    try:
        opt.solve(copy.deepcopy(rc01))
        res["solve_requires_registry"] = False
    except TypeError:
        res["solve_requires_registry"] = True
    default_reg = ControlledRegistry(tuple(approvals()))
    r = opt.solve(normalize_reference(reference_cases()["RC06"]), registry=default_reg)
    res["default_registry_denies_calendar_exception"] = (r["ignored_calendar_exceptions"],
                                                         next(a["start"] for a in r["activities"] if a["id"] == "N"))
    r = opt.solve(frozen_r0(5), registry=default_reg)
    res["default_registry_denies_fixture_exceptions"] = (r["status"], r["diagnostic"]["code"])
    bad = list(approvals())
    bad[0] = {**bad[0], "status": "APPROVED"}
    r = opt.solve(copy.deepcopy(rc01), registry=ControlledRegistry(tuple(bad)))
    res["registry_with_approved_row_rejected"] = (r["status"], r["diagnostic"]["code"])
    for name, mutate, want in [
        ("request supplies a registry field", lambda p: p.update(registry={"pending_approvals": []}), "UNSUPPORTED_CONSTRAINT"),
        ("request marks an approval APPROVED", lambda p: p["pending_approvals"][0].update(status="APPROVED"), "UNVERIFIED_APPROVAL"),
        ("request claims real-project scope", lambda p: p.update(scope="real_project"), "MODEL_INVALID"),
        ("request sets real_project_eligible", lambda p: p.update(real_project_eligible=True), "UNSUPPORTED_CONSTRAINT"),
        ("request adds fixture exceptions", lambda p: p.update(fixture_exceptions=[{"id": "FX-X"}]), "UNVERIFIED_FIXTURE_EXCEPTION"),
        ("engineer_approved input state", lambda p: p["activities"][0].update(input_state="engineer_approved"), "UNVERIFIED_APPROVAL"),
    ]:
        p = copy.deepcopy(rc01)
        mutate(p)
        r = research_engine.solve(p)
        res[f"gate: {name}"] = {"result": (r.get("diagnostic") or {}).get("code"), "expected": want,
                                "eligible": r["real_project_eligible"], "pass": (r.get("diagnostic") or {}).get("code") == want
                                and r["real_project_eligible"] is False and not r["activities"]}
    # --- interpreter separation
    probe = subprocess.run([sys.executable, "-B", "-c", "import sys, pmi_core.application, pmi_core.schedule_result; "
                            "print('ifcopenshell' in sys.modules, 'ortools' in sys.modules)"], cwd=REPO, capture_output=True, text=True)
    res["orchestrator_loads_neither_ifcopenshell_nor_ortools"] = probe.stdout.strip() == "False False"
    # --- output safety through the public unified contract
    cases = reference_cases()
    safety = {}
    for cid in ("RC12b", "RC13b", "RC12c", "RC07a", "RC08a", "RC01"):
        opt_res = research_engine.solve(normalize_reference(cases[cid]))
        unified = schedule_result(optimized=opt_res)
        proof = unified["proof"]
        safety[cid] = {"status": proof["status"], "schedule_scope": proof["schedule_scope"],
                       "project_makespan_minutes": proof["project_makespan_minutes"],
                       "makespan_by_scope_minutes": proof["makespan_by_scope_minutes"],
                       "internal_validated": unified["internal_timestamp_validated"]}
        complete = proof["schedule_scope"] == "complete_project"
        safety[cid]["safe"] = (complete and proof["project_makespan_minutes"] is not None) or \
                              (not complete and proof["project_makespan_minutes"] is None)
    res["output_safety"] = safety
    app_main = (REPO / "pmi_core/application.py").read_text(encoding="utf-8")
    res["application_exit_requires_complete_project"] = 'result["proof"]["schedule_scope"] == "complete_project"' in app_main
    # --- larger benchmark carries no IFC identities
    demo = research_engine.solve(construction_demo(False, version="v1.1"))
    unified = schedule_result(optimized=demo)
    committed = json.loads((REPO / "research/implementation/stage5_4b_integration/original_v1.1_schedule.json").read_text(encoding="utf-8"))
    res["benchmark_no_ifc_identity"] = {
        "fresh": {"source_ifc_sha256": unified["source_ifc_sha256"],
                  "any_ifc_global_id": any(a["ifc_global_id"] for a in unified["activities"]),
                  "any_canonical_element_id": any(a["canonical_element_id"] for a in unified["activities"])},
        "committed_export": {"source_ifc_sha256": committed.get("source_ifc_sha256"),
                             "any_ifc_global_id": any(a.get("ifc_global_id") for a in committed["activities"]),
                             "any_canonical_element_id": any(a.get("canonical_element_id") for a in committed["activities"])}}
    # --- C02 and C03
    c02 = json.loads((PKG / "corrections/C02_rc13b_acceptance_criterion_ref/c02_verification.json").read_text(encoding="utf-8"))
    rc13b = research_engine.solve(normalize_reference(cases["RC13b"]))
    res["C02"] = {"hash_ok": sha(PKG / c02["corrected_case"]["path"]) == c02["corrected_case"]["sha256"],
                  "output_ref": [e.get("acceptance_criterion_ref") for e in rc13b.get("strength_events", [])],
                  "status": rc13b["status"], "projection": rc13b["objective_minutes"]}
    from datetime import datetime
    from zoneinfo import ZoneInfo
    madrid, london = ZoneInfo("Europe/Madrid"), ZoneInfo("Europe/London")
    m = lambda s, z: int(datetime.fromisoformat(s).replace(tzinfo=z).timestamp() // 60)
    o, lim = m("2027-03-27T00:00", madrid), m("2027-11-02T00:00", madrid)
    lon = capacity_periods({"kind": "labour_trade", "unit": "worker", "calendar": {"timezone": "Europe/London"},
                            "capacity_by_date": {"2027-03-29": 0}}, 2, 1, madrid, o, lim, 5)
    cont = capacity_periods({"kind": "reusable_asset", "unit": "set", "calendar": "continuous",
                             "capacity_by_date": {"2027-03-28": 0, "2027-10-31": 1}}, 2, 1, madrid, o, lim, 5)
    res["C03"] = {"london_zero_window": [p for p in lon if p[2] == 0] == [(m("2027-03-29T00:00", london), m("2027-03-30T00:00", london), 0)],
                  "madrid_spring_1380": any(b - a == 1380 and v == 0 for a, b, v in cont),
                  "madrid_autumn_1500": any(b - a == 1500 and v == 1 for a, b, v in cont)}
    (OUT / "safety_verification.json").write_text(json.dumps(res, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
