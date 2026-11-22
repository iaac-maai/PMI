"""Write and verify the controlled R0 schedule in its source IFC4 model."""
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from uuid import NAMESPACE_URL, uuid5

from pmi_core.application import _digest
from pmi_core.viewer_data import build_viewer_data

R0_HASH = "8932ed0e043a1fb1252e51b223166c5c15b81f4969018a7e18c49e2802282c2c"
R0_MODEL = "8d21c70a-a957-58f3-88c4-123b7ac4f14b"
LABEL = "Hypothetical R0. Engineering approval pending. Construction use prohibited."
R0_START = datetime.fromisoformat("2027-01-04T08:00+01:00")

# SHA-256 of the committed Stage 5.4B.3 artifacts with LF line endings.
_ACCEPTED_REPLAY = {
    "73f514cba537d3233fa5e0314c2b2e1de68f84c1f381da586f57124c78fdc658",  # 5 min
    "6eac006e1f5009824370026f6e9f8edacaf7f8ec0b93818b73b39c6547d8e089",  # 15 min
}
# Same accepted artifacts reduced to stable JSON for comparison with a live run.
_ACCEPTED_LIVE = {
    "696056e14668b5155cef31c6c766e6e4ee3911911bcc707122e639ce7fee5ef1",  # 5 min
    "044928b21cd55c241e4a5e7378a8f0f0bc3cd0cbae808a0435230495413ed7b5",  # 15 min
}
_RUNTIME_FIELDS = {"runtime_seconds", "primary_runtime_seconds", "secondary_runtime_seconds",
                   "diagnostic_runtime_seconds"}



def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _dates(timing):
    start, finish = (datetime.fromisoformat(timing[key]) for key in ("start", "finish"))
    _require(start.utcoffset() is not None and finish.utcoffset() is not None
             and finish >= start, "Invalid offset-aware activity interval.")
    return start, finish


def _verify_timing(schedule, activities):
    finishes = []
    for key, activity in activities.items():
        timing = activity["optimized"]
        start, finish = _dates(timing)
        _require(R0_START <= start, f"Optimized activity precedes R0 project start: {key}.")
        # All registered R0 activities have a single segment, including elapsed holds.
        _require(len(timing["segments"]) == 1, f"Expected one optimized R0 segment: {key}.")
        segment_start, segment_finish = timing["segments"][0]
        _require(_dates({"start": segment_start, "finish": segment_finish}) == (start, finish),
                 f"Optimized segment does not match activity interval: {key}.")
        elapsed = (finish - start).total_seconds() / 60
        working = elapsed if activity["kind"] in {"productive", "inspection"} else 0
        for field, actual in (("elapsed_minutes", elapsed), ("working_minutes", working)):
            minutes = timing[field]
            _require(type(minutes) is int and minutes == actual == activity["baseline"][field],
                     f"Optimized {field} differs from the accepted R0 duration: {key}.")
        finishes.append(finish)

    proof = schedule["proof"]
    makespan = proof["project_makespan_minutes"]
    _require(type(makespan) is int and makespan == (max(finishes) - R0_START).total_seconds() / 60,
             "Optimized makespan differs from the recorded R0 project makespan.")
    _require(proof["solver_status"] == "OPTIMAL" and proof["lower_bound_minutes"] == makespan
             and proof["makespan_by_scope_minutes"]["complete_project"] == makespan
             and proof["optimality_gap"] == proof["optimality_gap_minutes"] == 0,
             "Optimal R0 proof does not match the project makespan and lower bound.")


def _verify_live_provenance(schedule, schedule_hash, run_digest):
    _require(schedule_hash == run_digest, "Schedule SHA-256 differs from the application run.")
    evidence = schedule.get("evidence")
    _require(isinstance(evidence, dict) and isinstance(evidence.get("runtimes"), dict)
             and {"ifc", "planning"} <= evidence["runtimes"].keys(),
             "Application scheduling provenance is incomplete.")
    # Only runtime measurements and interpreter metadata vary between accepted runs.
    stable = dict(schedule, proof={key: val for key, val in schedule["proof"].items()
                                   if key not in _RUNTIME_FIELDS},
                  evidence={key: val for key, val in evidence.items() if key != "runtimes"})
    canonical = json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()
    _require(sha256(canonical).hexdigest() in _ACCEPTED_LIVE,
             "Application schedule content or provenance differs from registered R0 evidence.")


def _metadata(schedule, schedule_hash):
    return dict(
        ModelVersionId=schedule["model_version_id"],
        SourceIfcSha256=schedule["source_ifc_sha256"],
        ScheduleSha256=schedule_hash,
        ScheduleContract=schedule["contract_version"],
        ScheduleScope=schedule["proof"]["schedule_scope"],
        TimestampSource=schedule["proof"]["timestamp_source"],
        InputState="hypothetical_fixture",
        ApprovalStatus="PENDING",
        PendingApprovalCount=len(schedule["pending_approvals"]),
        RealProjectEligible=False,
    )


def _task_metadata(activity):
    return dict(
        WorkPackageId=activity["work_package_id"],
        CanonicalElementId=activity["canonical_element_id"],
        InputState=activity["input_state"],
        ApprovalStatus="PENDING",
        ApprovalIds=json.dumps(activity["approval_ids"]),
        EvidenceReference=activity["evidence_ref"],
    )


def _index(rows, key):
    indexed = {row[key]: row for row in rows}
    _require(len(indexed) == len(rows), f"Duplicate {key}.")
    return indexed


def _controlled(source, schedule, model):
    _require(schedule.get("contract_version") == "pmi-schedule/1"
             and schedule.get("source_ifc_sha256") == R0_HASH == _digest(source)
             and schedule.get("model_version_id") == R0_MODEL
             and schedule.get("project_id") == "PMI-CONTROLLED",
             "Only the registered IFC-backed R0 model and schedule are supported.")
    _require(model.schema == "IFC4", "R0 requires IFC4.")
    _require(schedule["real_project_eligible"] is False and len(schedule["pending_approvals"]) == 88
             and all(row["status"] == "PENDING" for row in schedule["pending_approvals"])
             and schedule["internal_timestamp_validated"] is True
             and schedule["proof"]["status"] == "OPTIMAL"
             and schedule["proof"]["solver_scope"] == "controlled"
             and schedule["proof"]["schedule_scope"] == "complete_project",
             "Expected a validated controlled R0 schedule with pending approvals.")
    activities = _index(schedule["activities"], "activity_id")
    packages = _index(schedule["work_packages"], "id")
    _require(len(activities) == 21 and len(packages) == 3, "Incomplete R0 schedule.")
    elements = {element.GlobalId: element for element in model.by_type("IfcElement")}
    _require(len(elements) == 3, "Expected three R0 source elements.")
    _require({activity["ifc_global_id"] for activity in activities.values()}
             == elements.keys(), "R0 source element mapping differs.")
    for activity in activities.values():
        package = packages[activity["work_package_id"]]
        _require(activity["input_state"] == "hypothetical_fixture" and activity["approval_ids"]
                 and activity["ifc_global_id"] in package["global_ids"]
                 and activity["canonical_element_id"] in package["element_ids"],
                 "Invalid R0 activity provenance or package membership.")
        _dates(activity["optimized"])
        _dates(activity["baseline"])
    for package_id, package in packages.items():
        members = {key for key, row in activities.items() if row["work_package_id"] == package_id}
        _require(len(members) == 7 and members == set(package["activity_ids"]),
                 "Invalid R0 package membership.")
    edges = set()
    for edge in schedule["dependencies"]:
        pred, succ = edge["predecessor_id"], edge["successor_id"]
        _require(pred in activities and succ in activities and pred != succ
                 and (edge["relation"], edge["lag_minutes"], edge["lag_basis"]) == ("FS", 0, "elapsed")
                 and _dates(activities[pred]["optimized"])[1] <= _dates(activities[succ]["optimized"])[0],
                 "Invalid or unsupported R0 dependency.")
        edges.add((pred, succ))
    _require(len(edges) == len(schedule["dependencies"]) == 28, "Incomplete or duplicate R0 dependencies.")
    _verify_timing(schedule, activities)
    return activities, packages, elements


def _populate(model, schedule, schedule_hash, activities, packages, elements):
    from ifcopenshell import guid

    def root(ifc_class, key, **attrs):
        identity = uuid5(NAMESPACE_URL, f"pmi-ifc4d/{R0_MODEL}/{ifc_class}/{key}")
        return model.create_entity(ifc_class, GlobalId=guid.compress(identity.hex), **attrs)

    def properties(owner, name, fields):
        types = {str: "IfcText", bool: "IfcBoolean", int: "IfcInteger"}
        props = [model.create_entity("IfcPropertySingleValue", Name=key,
                                     NominalValue=model.create_entity(types[type(value)], value))
                 for key, value in fields.items()]
        key = owner.GlobalId
        pset = root("IfcPropertySet", key, Name=name, HasProperties=props)
        root("IfcRelDefinesByProperties", key, RelatedObjects=[owner], RelatingPropertyDefinition=pset)

    intervals = [_dates(row["optimized"]) for row in activities.values()]
    start = min(pair[0] for pair in intervals).isoformat()
    finish = max(pair[1] for pair in intervals).isoformat()
    # Use the frozen source authoring timestamp for reproducible exports.
    created = model.header.file_name.time_stamp
    plan = root("IfcWorkPlan", "plan", Name="PMI R0 hypothetical work plan", Description=LABEL,
                CreationDate=created, StartTime=start, FinishTime=finish, PredefinedType="PLANNED")
    work = root("IfcWorkSchedule", "schedule", Name="PMI R0 CP-SAT schedule", Description=LABEL,
                CreationDate=created, StartTime=start, FinishTime=finish, PredefinedType="PLANNED")
    root("IfcRelDeclares", "plan", RelatingContext=model.by_type("IfcProject")[0], RelatedDefinitions=[plan])
    root("IfcRelAggregates", "schedule", RelatingObject=plan, RelatedObjects=[work])
    properties(work, "PMI_ScheduleProvenance", _metadata(schedule, schedule_hash))

    tasks = {}
    for activity_id, row in activities.items():
        optimized = row["optimized"]
        timing = model.create_entity("IfcTaskTime", DataOrigin="PREDICTED",
                                     ScheduleStart=_dates(optimized)[0].isoformat(),
                                     ScheduleFinish=_dates(optimized)[1].isoformat())
        task = root("IfcTask", activity_id, Identification=activity_id, Name=row["reference_id"],
                    Description=LABEL, Status="HYPOTHETICAL - APPROVAL PENDING",
                    IsMilestone=False, PredefinedType="CONSTRUCTION", TaskTime=timing)
        tasks[activity_id] = task
        properties(task, "PMI_ActivityProvenance", _task_metadata(row))
        root("IfcRelAssignsToProcess", activity_id, RelatingProcess=task,
             RelatedObjects=[elements[row["ifc_global_id"]]])

    package_tasks = []
    for package_id, package in packages.items():
        parent = root("IfcTask", package_id, Identification=package_id, Name=package["family"],
                      Description=LABEL, Status="HYPOTHETICAL - APPROVAL PENDING",
                      IsMilestone=False, PredefinedType="NOTDEFINED")
        package_tasks.append(parent)
        root("IfcRelNests", package_id, RelatingObject=parent,
             RelatedObjects=[tasks[key] for key in package["activity_ids"]])
    root("IfcRelAssignsToControl", "schedule", RelatingControl=work, RelatedObjects=package_tasks)

    for edge in schedule["dependencies"]:
        pred, succ = edge["predecessor_id"], edge["successor_id"]
        root("IfcRelSequence", f"{pred}/{succ}", RelatingProcess=tasks[pred],
             RelatedProcess=tasks[succ], SequenceType="FINISH_START",
             Description=json.dumps(edge, sort_keys=True))


def _verify(source, target, schedule, schedule_hash, activities, packages, elements):
    import ifcopenshell
    from ifcopenshell.util.element import get_pset
    from ifcopenshell.validate import json_logger, validate

    original = ifcopenshell.open(str(source))
    reopened = ifcopenshell.open(str(target))
    # Compare every original STEP instance, including unit definitions, contexts,
    # placements, shape representations and their complete referenced geometry.
    _require(all(str(entity) == str(reopened.by_id(entity.id())) for entity in original),
             "Source IFC instances changed during export.")
    _require({item.GlobalId for item in reopened.by_type("IfcElement")} == elements.keys(),
             "Re-imported IFC element identities differ.")

    logger = json_logger()
    validate(reopened, logger)
    _require(not logger.statements, f"IFC4 validation failed: {logger.statements[:3]}")
    tasks = {task.Identification: task for task in reopened.by_type("IfcTask")}
    _require(len(tasks) == len(reopened.by_type("IfcTask")) and tasks.keys() == activities.keys() | packages.keys(),
             "Re-imported task identities differ.")
    work, = reopened.by_type("IfcWorkSchedule")
    plan, = reopened.by_type("IfcWorkPlan")
    _require(any(link.RelatingObject == plan and work in link.RelatedObjects
                 for link in reopened.by_type("IfcRelAggregates")), "Schedule is outside its work plan.")
    _require({item.Identification for rel in work.Controls for item in rel.RelatedObjects} == packages.keys(),
             "Re-imported schedule package identities differ.")
    props = get_pset(work, "PMI_ScheduleProvenance")
    _require({key: value for key, value in props.items() if key != "id"} == _metadata(schedule, schedule_hash)
             and work.Description == LABEL and plan.Description == LABEL,
             "Schedule provenance or use restriction differs.")

    recovered = {}
    for key, expected in activities.items():
        task = tasks[key]
        time = task.TaskTime
        actual = dict(start=time.ScheduleStart, finish=time.ScheduleFinish)
        _require(tuple(instant.isoformat() for instant in _dates(actual)) ==
                 tuple(instant.isoformat() for instant in _dates(expected["optimized"])),
                 f"Re-imported timestamp differs for {key}.")
        assignments = [item.GlobalId for rel in task.OperatesOn for item in rel.RelatedObjects]
        props = get_pset(task, "PMI_ActivityProvenance")
        _require(assignments == [expected["ifc_global_id"]]
                 and {name: value for name, value in props.items() if name != "id"} == _task_metadata(expected)
                 and task.Description == LABEL
                 and time.ActualStart is None and time.ActualFinish is None,
                 f"Re-imported activity assignment or provenance differs for {key}.")
        recovered[key] = dict(actual, task_global_id=task.GlobalId, element_global_id=assignments[0],
                              work_package_id=expected["work_package_id"])
    for key, package in packages.items():
        _require([item.Identification for rel in tasks[key].IsNestedBy for item in rel.RelatedObjects]
                 == package["activity_ids"], f"Re-imported package members differ for {key}.")

    edges = []
    for rel in reopened.by_type("IfcRelSequence"):
        edge = json.loads(rel.Description)
        _require((rel.RelatingProcess.Identification, rel.RelatedProcess.Identification,
                  rel.SequenceType, rel.TimeLag) ==
                 (edge["predecessor_id"], edge["successor_id"], "FINISH_START", None),
                 "Re-imported dependency relationship differs.")
        edges.append(edge)
    _require(sorted(map(json.dumps, edges)) == sorted(
        json.dumps(edge, sort_keys=True) for edge in schedule["dependencies"]),
        "Re-imported dependency metadata differs.")
    return dict(
        status="PASS", ifc_schema=reopened.schema, ifc_validation_issues=0,
        original_step_instances_verified=sum(1 for _ in original),
        source_element_global_ids=sorted(elements), activities=recovered,
        packages={key: tasks[key].GlobalId for key in packages}, dependencies=edges,
        provenance=_metadata(schedule, schedule_hash), restriction=LABEL,
        output_ifc_sha256=_digest(target),
    )


def export_controlled_ifc4d(source, schedule_path, output):
    """Replay a registered, independently accepted R0 artifact."""
    return _export(source, schedule_path, output)


def _export_live(source, schedule_path, output, run_digest):
    """Export the schedule just produced by the application orchestrator."""
    return _export(source, schedule_path, output, run_digest=run_digest)


def _export(source, schedule_path, output, *, run_digest=None):
    import ifcopenshell

    source, schedule_path, output = map(Path, (source, schedule_path, output))
    _require(not output.exists(), "IFC4D output directory already exists.")
    payload = schedule_path.read_bytes()
    schedule = json.loads(payload.decode("utf-8-sig"))
    schedule_hash = sha256(payload).hexdigest()
    model = ifcopenshell.open(str(source))
    activities, packages, elements = _controlled(source, schedule, model)
    if run_digest is None:
        # Allow Git checkout line-ending conversion while preserving the exact
        # input bytes' digest in the export for traceability.
        registered_digest = sha256(payload.replace(b"\r\n", b"\n")).hexdigest()
        _require(registered_digest in _ACCEPTED_REPLAY,
                 "Schedule SHA-256 does not match a registered accepted R0 artifact.")
    else:
        _verify_live_provenance(schedule, schedule_hash, run_digest)
    _populate(model, schedule, schedule_hash, activities, packages, elements)
    with tempfile.TemporaryDirectory(dir=output.parent) as staging:
        bundle = Path(staging) / "bundle"
        bundle.mkdir()
        target = bundle / "scheduled.ifc"
        model.write(str(target))
        evidence = _verify(source, target, schedule, schedule_hash, activities, packages, elements)
        viewer = build_viewer_data(schedule, evidence)
        for name, payload in (("round_trip.json", evidence), ("viewer.json", viewer)):
            (bundle / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        bundle.rename(output.resolve())
    return evidence


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("source", "schedule", "output"):
        parser.add_argument(f"--{arg}", type=Path, required=True)
    args = parser.parse_args()
    try:
        export_controlled_ifc4d(args.source, args.schedule, args.output)
    except (KeyError, TypeError, ValueError, RuntimeError, OSError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
