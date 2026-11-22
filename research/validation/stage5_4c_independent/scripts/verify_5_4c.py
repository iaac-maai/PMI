"""Independent Stage 5.4C IFC4D verification. Run from the repo root with the IFC interpreter:

    .venv/Scripts/python.exe -B research/validation/stage5_4c_independent/scripts/verify_5_4c.py

Checks are independent of the exporter's own round-trip checker:
  * raw STEP text comparison of every source instance (no IfcOpenShell involved);
  * IFC4D semantics read back through IfcOpenShell inverse relationships by this script;
  * schedule reconciliation against the accepted Stage 5.4B.3 artifacts and, in the planning interpreter,
    against the independent Stage 5.4A model (verify_core.check_r0);
  * negative tests against the exporter CLI and the application.
"""

import copy
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
REPO = HERE.parents[3]
IFCPY = REPO / ".venv/Scripts/python.exe"
PLAN = REPO / ".venv-planning/Scripts/python.exe"
SOURCE = REPO / "research/implementation/stage5_2/controlled_frame.ifc"
CONFIG = REPO / "research/implementation/stage5_4b_integration/r0_config.json"
ACCEPTED = REPO / "research/implementation/stage5_4b_integration"
R0_HASH = "8932ed0e043a1fb1252e51b223166c5c15b81f4969018a7e18c49e2802282c2c"

import ifcopenshell  # noqa: E402  (reader only; the exporter is exercised through its CLI)
import ifcopenshell.geom  # noqa: E402


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def step_instances(path):
    """Parse '#id=ENTITY(...);' records from the DATA section as raw text (handles multi-line records)."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    data = text.split("DATA;", 1)[1].rsplit("ENDSEC;", 1)[0]
    records, buf = {}, ""
    for line in data.splitlines():
        buf += line.strip()
        if buf.endswith(";"):
            m = re.match(r"#(\d+)\s*=\s*(.*);$", buf)
            if m:
                records[int(m.group(1))] = re.sub(r"\s+", "", m.group(2))
            buf = ""
    return records


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], cwd=REPO, capture_output=True, text=True, **kw)


def pipeline(tick, out):
    return run([PLAN, "-B", "-m", "pmi_core.application", "--config", CONFIG, "--output", out, "--tick", tick,
                "--ifc4d", "--ifc-python", IFCPY, "--planning-python", PLAN])


def check_bundle(tick, run_dir, src_records, src_model):
    sched = json.loads((run_dir / "schedule.json").read_text(encoding="utf-8"))
    bundle = run_dir / "ifc4d"
    ifc_path, viewer = bundle / "scheduled.ifc", json.loads((bundle / "viewer.json").read_text(encoding="utf-8"))
    r = {}
    # ---- source preservation (raw STEP text, library-independent)
    out_records = step_instances(ifc_path)
    changed = [i for i, body in src_records.items() if out_records.get(i) != body]
    r["source_instances"] = len(src_records)
    r["source_instances_byte_identical"] = not changed
    r["new_instances"] = len(out_records) - len(src_records)
    new_types = {}
    for i, body in out_records.items():
        if i not in src_records:
            t = body.split("(", 1)[0]
            new_types[t] = new_types.get(t, 0) + 1
    r["new_instance_types"] = dict(sorted(new_types.items()))
    r["no_new_geometry_or_elements"] = not any(t in new_types for t in (
        "IFCCOLUMN", "IFCBEAM", "IFCSLAB", "IFCSHAPEREPRESENTATION", "IFCEXTRUDEDAREASOLID", "IFCLOCALPLACEMENT",
        "IFCCARTESIANPOINT", "IFCSIUNIT", "IFCELEMENTQUANTITY", "IFCQUANTITYVOLUME"))
    model = ifcopenshell.open(str(ifc_path))
    r["schema"] = model.schema
    # ---- geometry, placements, units, quantities via IfcOpenShell (world-coordinate meshes)
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)

    def meshes(m):
        return {e.GlobalId: (tuple(round(v, 9) for v in ifcopenshell.geom.create_shape(settings, e).geometry.verts))
                for e in m.by_type("IfcElement")}
    r["element_global_ids"] = sorted(e.GlobalId for e in model.by_type("IfcElement"))
    r["geometry_identical"] = meshes(model) == meshes(src_model)
    units = lambda m: sorted(str(u.UnitType) + ":" + str(getattr(u, "Prefix", None)) + ":" + str(getattr(u, "Name", None))  # noqa: E731
                             for u in m.by_type("IfcSIUnit"))
    r["units_identical"] = units(model) == units(src_model)

    def quantities(m):
        out = {}
        for e in m.by_type("IfcElement"):
            for rel in e.IsDefinedBy:
                d = rel.RelatingPropertyDefinition
                if d.is_a("IfcElementQuantity"):
                    for q in d.Quantities:
                        out[(e.GlobalId, d.Name, q.Name)] = q[3]
        return out
    r["authored_quantities"] = len(quantities(src_model))
    r["authored_quantities_identical"] = quantities(model) == quantities(src_model)
    # ---- IFC4D semantics
    acts = {a["activity_id"]: a for a in sched["activities"]}
    pkgs = {p["id"]: p for p in sched["work_packages"]}
    project, = model.by_type("IfcProject")
    plans = [d for rel in project.Declares for d in rel.RelatedDefinitions if d.is_a("IfcWorkPlan")]
    plan, = plans
    works = [o for rel in plan.IsDecomposedBy for o in rel.RelatedObjects if o.is_a("IfcWorkSchedule")]
    work, = works
    controlled = [o for rel in work.Controls for o in rel.RelatedObjects]
    tasks = {t.Identification: t for t in model.by_type("IfcTask")}
    nested = {p.Identification: [c.Identification for rel in p.IsNestedBy for c in rel.RelatedObjects] for p in controlled}
    r["hierarchy"] = {"plan_declared_by_project": True, "schedule_aggregated_by_plan": True,
                      "package_tasks_controlled_by_schedule": sorted(t.Identification for t in controlled) == sorted(pkgs),
                      "package_members_ordered_equal_schedule": all(nested[k] == pkgs[k]["activity_ids"] for k in pkgs),
                      "tasks_total": len(tasks)}
    sched_start = min(datetime.fromisoformat(a["optimized"]["start"]) for a in acts.values())
    sched_finish = max(datetime.fromisoformat(a["optimized"]["finish"]) for a in acts.values())
    r["work_schedule_span_matches"] = (datetime.fromisoformat(work.StartTime) == sched_start
                                       and datetime.fromisoformat(work.FinishTime) == sched_finish)
    time_err, assign_err, offsets = [], [], set()
    for k, a in acts.items():
        t = tasks[k]
        tt = t.TaskTime
        s, f = datetime.fromisoformat(tt.ScheduleStart), datetime.fromisoformat(tt.ScheduleFinish)
        offsets |= {tt.ScheduleStart[19:], tt.ScheduleFinish[19:]}
        if (s, f) != (datetime.fromisoformat(a["optimized"]["start"]), datetime.fromisoformat(a["optimized"]["finish"])):
            time_err.append(k)
        if tt.DataOrigin != "PREDICTED" or tt.ActualStart or tt.ActualFinish:
            time_err.append(k + ":origin")
        operates = [o.GlobalId for rel in t.OperatesOn for o in rel.RelatedObjects]
        if operates != [a["ifc_global_id"]]:
            assign_err.append(k)
    r["activity_tasks"] = len(acts)
    r["task_times_equal_cp_sat"] = not time_err
    r["timestamp_offsets"] = sorted(offsets)
    r["assignments"] = sum(len(rel.RelatedObjects) for rel in model.by_type("IfcRelAssignsToProcess"))
    r["assignments_correct"] = not assign_err and r["assignments"] == 21
    per_element = {}
    for rel in model.by_type("IfcRelAssignsToProcess"):
        for o in rel.RelatedObjects:
            per_element[o.GlobalId] = per_element.get(o.GlobalId, 0) + 1
    r["assignments_per_element"] = per_element
    seqs = {(s.RelatingProcess.Identification, s.RelatedProcess.Identification): s for s in model.by_type("IfcRelSequence")}
    deps = {(d["predecessor_id"], d["successor_id"]) for d in sched["dependencies"]}
    r["sequence_edges"] = len(seqs)
    r["sequences_equal_dependencies_and_directed"] = set(seqs) == deps and all(
        s.SequenceType == "FINISH_START" and s.TimeLag is None for s in seqs.values())
    r["sequences_respected_by_task_times"] = all(
        datetime.fromisoformat(tasks[p].TaskTime.ScheduleFinish) <= datetime.fromisoformat(tasks[q].TaskTime.ScheduleStart)
        for p, q in seqs)
    kinds = {}
    for a in acts.values():
        kinds.setdefault(a["kind"], set()).add(tasks[a["activity_id"]].PredefinedType)
    r["task_predefined_type_by_activity_kind"] = {k: sorted(v) for k, v in kinds.items()}
    # ---- viewer contract
    v = viewer
    resolved = (bundle / v["model"]["uri"]).resolve()
    r["viewer"] = {
        "uri_resolves_to_export": resolved == ifc_path.resolve(),
        "sha256_matches": v["model"]["sha256"] == sha(ifc_path),
        "activities": len(v["activities_by_id"]),
        "every_activity_maps_to_source_element": all(
            x["element_global_ids"] and set(x["element_global_ids"]) <= set(r["element_global_ids"]) for x in v["activities_by_id"].values()),
        "reverse_mapping_complete": sorted(a for ids in v["activity_ids_by_element_global_id"].values() for a in ids) == sorted(acts)
        and all(k in v["activity_ids_by_element_global_id"][x["element_global_ids"][0]] for k, x in v["activities_by_id"].items()),
        "cpm_and_cp_sat_separate": all(set(x["cpm"]) != set(x["cp_sat"]) and "cpm_critical" in x["cpm"] and "cpm_critical" not in x["cp_sat"]
                                       for x in v["activities_by_id"].values()),
        "cp_sat_segments_available": all(x["cp_sat"].get("segments") for x in v["activities_by_id"].values()),
        "dependencies_complete_and_directed": {(d["predecessor_id"], d["successor_id"]) for d in v["dependencies"]} == deps,
        "task_global_ids_match_ifc": all(x["ifc_task_global_id"] == tasks[k].GlobalId for k, x in v["activities_by_id"].items()),
        "pending_and_restriction_visible": v["status"]["ApprovalStatus"] == "PENDING" and v["status"]["PendingApprovalCount"] == 88
        and v["status"]["RealProjectEligible"] is False and "Construction use prohibited" in v["restriction"]
        and all(x["approval_status"] == "PENDING" and x["approval_ids"] for x in v["activities_by_id"].values()),
        "cpm_equals_cp_sat_dates_for_r0": all(x["cpm"]["start"] == x["cp_sat"]["start"] for x in v["activities_by_id"].values()),
        "packages": len(v["packages"]),
        "has_project_makespan_or_proof": any(k in v for k in ("proof", "project_makespan_minutes")) or "proof" in v.get("status", {}),
        "has_critical_path_edges": "cpm" in v and "critical_edges" in v.get("cpm", {}),
        "has_resource_occupancy": "resource_occupancy" in v,
        "has_calendar": "calendar" in v or "project_calendar" in v,
    }
    # ---- schedule against accepted 5.4B.3 artifact (everything except runtime-like fields)
    acc = json.loads((ACCEPTED / f"r0_{tick}_schedule.json").read_text(encoding="utf-8"))
    def norm(s):
        s = copy.deepcopy(s)
        for k in ("evidence",):
            s.pop(k, None)
        for k in list(s["proof"]):
            if "runtime" in k:
                s["proof"].pop(k)
        return s
    r["schedule_equals_accepted_5_4b3"] = norm(sched) == norm(acc)
    r["proof"] = {k: sched["proof"][k] for k in ("status", "schedule_scope", "project_makespan_minutes", "lower_bound_minutes")}
    r["cost"] = sched["cost"]["total_direct_reference_eur"]
    r["work_packages"] = len(sched["work_packages"])
    r["pending_approvals"] = len(sched["pending_approvals"])
    r["real_project_eligible"] = sched["real_project_eligible"]
    r["ifc_sha256"] = sha(ifc_path)
    return r, sched


def main():
    started = {p: sha(REPO / p) for p in ("pmi_core/application.py", "pmi_core/adapters/ifc4d.py", "pmi_core/viewer_data.py",
                                           "tests/test_ifc4d_r0.py")}
    head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    src_records = step_instances(SOURCE)
    src_model = ifcopenshell.open(str(SOURCE))
    tmp = Path(tempfile.mkdtemp(prefix="pmi_54c_"))
    result = {"head": head, "source_ifc_sha256": sha(SOURCE)}
    try:
        runs = {}
        for tick in (5, 15):
            d = tmp / f"r0_{tick}"
            p = pipeline(tick, d)
            res, sched = check_bundle(tick, d, src_records, src_model)
            res["exit_code"] = p.returncode
            runs[tick] = res
            # independent Stage 5.4A model on the produced schedule (planning interpreter)
            code = ("import json,sys;sys.path.insert(0,'research/validation/stage5_4b_independent/core/scripts');"
                    "sys.path.insert(0,'research/validation/stage5_4a_independent_verification/scripts');import verify_core as c;"
                    f"s=json.load(open(r'{d / 'schedule.json'}',encoding='utf-8'));"
                    "dem={};[dem.setdefault(r['holder_id'],{}).__setitem__(r['resource_id'],r['demand']) for r in s['resource_occupancy'] if r['occupancy_basis']=='working_time'];"
                    "acts=[{'reference_id':a['reference_id'],'start':a['optimized']['start'],'finish':a['optimized']['finish'],'segments':a['optimized']['segments'],'resources':dem.get(a['activity_id'],{})} for a in s['activities']];"
                    f"e,i=c.check_r0({tick},{{'activities':acts,'objective_minutes':s['proof']['project_makespan_minutes']}});print(json.dumps([e,i]))")
            out = run([PLAN, "-B", "-c", code])
            errs, info = json.loads(out.stdout)
            res["independent_stage5_4a_errors"] = errs
            res["independent_cpm_makespan"] = info["independent_cpm_makespan"]
        result["runs"] = runs
        result["task_guids_stable_across_ticks"] = None
        g = {}
        for tick in (5, 15):
            m = ifcopenshell.open(str(tmp / f"r0_{tick}" / "ifc4d/scheduled.ifc"))
            g[tick] = {t.Identification: t.GlobalId for t in m.by_type("IfcTask")}
        result["task_guids_stable_across_ticks"] = g[5] == g[15]

        # ---- negative tests (exporter CLI in the IFC interpreter)
        neg = {}
        sched_path = tmp / "r0_5" / "schedule.json"
        base = json.loads(sched_path.read_text(encoding="utf-8"))

        def export(schedule_obj=None, schedule_file=None, source=SOURCE, out=None):
            out = out or (tmp / "neg" / f"o{len(neg)}")
            out.parent.mkdir(exist_ok=True)
            if schedule_obj is not None:
                schedule_file = tmp / "neg" / f"s{len(neg)}.json"
                schedule_file.write_text(json.dumps(schedule_obj), encoding="utf-8")
            p = run([IFCPY, "-B", "-m", "pmi_core.adapters.ifc4d", "--source", source, "--schedule", schedule_file, "--output", out])
            leftovers = [x.name for x in out.parent.iterdir() if x.name.startswith("tmp")]
            return {"exit": p.returncode, "output_created": out.exists(), "staging_leftovers": leftovers,
                    "message": (p.stderr or p.stdout).strip()[-140:]}

        def mutated(fn):
            s = copy.deepcopy(base)
            fn(s)
            return s
        neg["C01 v1.1 schedule (no IFC identity)"] = export(schedule_file=ACCEPTED / "original_v1.1_schedule.json")
        altered_ifc = tmp / "altered.ifc"
        altered_ifc.write_bytes(SOURCE.read_bytes().replace(b"ENDSEC;", b"/* altered */ENDSEC;", 1))
        neg["altered IFC bytes with R0 schedule"] = export(schedule_obj=base, source=altered_ifc)
        other = REPO / "research/implementation/stage5_4c/scheduled.ifc"
        neg["different IFC (exported example) as source"] = export(schedule_obj=base, source=other)
        neg["approval APPROVED"] = export(mutated(lambda s: s["pending_approvals"][0].update(status="APPROVED")))
        neg["approval removed (87)"] = export(mutated(lambda s: s["pending_approvals"].pop()))
        neg["real_project_eligible true"] = export(mutated(lambda s: s.update(real_project_eligible=True)))
        neg["dependency removed"] = export(mutated(lambda s: s["dependencies"].pop()))
        neg["dependency duplicated"] = export(mutated(lambda s: (s["dependencies"].pop(), s["dependencies"].append(dict(s["dependencies"][0])))))
        neg["dependency reversed"] = export(mutated(lambda s: s["dependencies"][0].update(
            predecessor_id=s["dependencies"][0]["successor_id"], successor_id=s["dependencies"][0]["predecessor_id"])))
        neg["dependency unknown endpoint"] = export(mutated(lambda s: s["dependencies"][0].update(successor_id="X")))
        neg["dependency nonzero lag"] = export(mutated(lambda s: s["dependencies"][0].update(lag_minutes=15)))
        neg["activity mapped to unknown element"] = export(mutated(lambda s: s["activities"][0].update(ifc_global_id="0" * 22)))
        neg["conditional scope"] = export(mutated(lambda s: s["proof"].update(schedule_scope="conditional_projection")))

        def forged(s):
            last = max(s["activities"], key=lambda a: a["optimized"]["finish"])
            for key in ("start", "finish"):
                last["optimized"][key] = last["optimized"][key].replace("T", "T", 1)
            # shift the final activity one day later, keeping it after all predecessors
            from datetime import timedelta
            st, fi = (datetime.fromisoformat(last["optimized"][k]) + timedelta(days=1) for k in ("start", "finish"))
            last["optimized"].update(start=st.isoformat(timespec="minutes"), finish=fi.isoformat(timespec="minutes"),
                                     segments=[[st.isoformat(timespec="minutes"), fi.isoformat(timespec="minutes")]])
        neg["forged consistent date shift (makespan not updated)"] = export(mutated(forged))
        existing = tmp / "neg" / "existing"
        existing.mkdir(parents=True)
        (existing / "scheduled.ifc").write_bytes(b"existing")
        e = export(schedule_obj=base, out=existing)
        e["existing_preserved"] = (existing / "scheduled.ifc").read_bytes() == b"existing" and len(list(existing.iterdir())) == 1
        neg["existing output directory"] = e
        # application path: existing output directory
        p = pipeline(5, tmp / "r0_5")
        neg["application into existing output"] = {"exit": p.returncode, "message": (p.stderr or p.stdout).strip()[-120:],
                                                   "previous_bundle_preserved": sha(tmp / "r0_5/ifc4d/scheduled.ifc") == runs[5]["ifc_sha256"]}
        result["negative_tests"] = neg
        # ---- EXPRESS rule availability (no installation)
        probe = run([IFCPY, "-B", "-c", "import ifcopenshell.validate as v, inspect; print('express_rules' in inspect.signature(v.validate).parameters)"])
        express = run([IFCPY, "-B", "-c", "import ifcopenshell, ifcopenshell.validate as v, ifcopenshell.express.rule_executor as r; print('rule_executor importable')"])
        result["express_rules"] = {"validate_accepts_express_rules_flag": probe.stdout.strip(),
                                   "rule_executor_import": (express.stdout or express.stderr).strip().splitlines()[-1][:200]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ended = {p: sha(REPO / p) for p in started}
    result["implementation_stable_during_run"] = started == ended
    result["implementation_sha256"] = started
    (OUT / "independent_ifc4d_results.json").write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1, default=str))


if __name__ == "__main__":
    main()
