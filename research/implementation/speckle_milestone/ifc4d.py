"""Export and re-import the milestone schedule inside a trusted application run."""
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import ifcopenshell
from ifcopenshell.guid import compress
from ifcopenshell.validate import json_logger, validate

from pmi_core.adapters.ifc4d import _dates, _metadata, _task_metadata
from pmi_core.application import _digest, _read
from pmi_core.viewer_data import build_viewer_data

NOTICE = "CONTROLLED HYPOTHETICAL DEMONSTRATION — NOT AUTHORIZED FOR CONSTRUCTION USE."


def require(test, message):
    if not test:
        raise ValueError(message)


def export_in_run(folder, *, source_digest, schedule_digest):
    folder = Path(folder)
    source, schedule_path = folder / "source.ifc", folder / "schedule.json"
    require(_digest(source) == source_digest and _digest(schedule_path) == schedule_digest,
            "Run inputs differ from their recorded digests.")
    schedule = _read(schedule_path)
    require(schedule["source_ifc_sha256"] == source_digest
            and schedule["internal_timestamp_validated"] is True
            and schedule["proof"]["status"] == "OPTIMAL"
            and schedule["proof"]["schedule_scope"] == "complete_project"
            and schedule["real_project_eligible"] is False and len(schedule["pending_approvals"]) == 88
            and all(row["status"] == "PENDING" for row in schedule["pending_approvals"]),
            "Expected a validated controlled schedule with pending engineering approvals.")
    model = ifcopenshell.open(str(source))
    original = {entity.id(): str(entity) for entity in model}
    elements = {obj.GlobalId: obj for obj in model.by_type("IfcElement")}
    activities = {row["activity_id"]: row for row in schedule["activities"]}
    packages = {row["id"]: row for row in schedule["work_packages"]}
    require(model.schema == "IFC4" and {row["ifc_global_id"] for row in activities.values()} == elements.keys(),
            "Source IFC and scheduled products differ.")
    require(len(activities) == len(schedule["activities"]) and activities.keys().isdisjoint(packages),
            "Duplicate task identities.")

    def root(kind, key, **attrs):
        identity = compress(uuid5(NAMESPACE_URL, f"pmi-speckle/{source_digest}/{kind}/{key}").hex)
        return model.create_entity(kind, GlobalId=identity, **attrs)

    def properties(owner, name, fields):
        types = {str: "IfcText", bool: "IfcBoolean", int: "IfcInteger"}
        values = [model.create_entity("IfcPropertySingleValue", Name=key,
                                      NominalValue=model.create_entity(types[type(value)], value))
                  for key, value in fields.items()]
        group = root("IfcPropertySet", owner.GlobalId, Name=name, HasProperties=values)
        root("IfcRelDefinesByProperties", owner.GlobalId, RelatedObjects=[owner],
             RelatingPropertyDefinition=group)

    times = {key: _dates(row["optimized"]) for key, row in activities.items()}
    start, end = min(row[0] for row in times.values()), max(row[1] for row in times.values())
    details = dict(Description=NOTICE, CreationDate=model.header.file_name.time_stamp,
                   StartTime=start.isoformat(), FinishTime=end.isoformat(), PredefinedType="PLANNED")
    plan = root("IfcWorkPlan", "plan", Name="PMI controlled plan", **details)
    work = root("IfcWorkSchedule", "schedule", Name="PMI controlled CP-SAT", **details)
    root("IfcRelDeclares", "plan", RelatingContext=model.by_type("IfcProject")[0], RelatedDefinitions=[plan])
    root("IfcRelAggregates", "schedule", RelatingObject=plan, RelatedObjects=[work])
    metadata = _metadata(schedule, schedule_digest)
    properties(work, "PMI_ScheduleProvenance", metadata)
    tasks = {}
    for key, row in activities.items():
        task_time = model.create_entity("IfcTaskTime", DataOrigin="PREDICTED",
                                        ScheduleStart=times[key][0].isoformat(),
                                        ScheduleFinish=times[key][1].isoformat())
        task = root("IfcTask", key, Identification=key, Name=row["reference_id"], Description=NOTICE,
                    Status="HYPOTHETICAL - APPROVAL PENDING", IsMilestone=False,
                    PredefinedType="CONSTRUCTION", TaskTime=task_time)
        tasks[key] = task
        properties(task, "PMI_ActivityProvenance", _task_metadata(row))
        root("IfcRelAssignsToProcess", key, RelatingProcess=task,
             RelatedObjects=[elements[row["ifc_global_id"]]])
    parents = []
    for key, row in packages.items():
        parent = root("IfcTask", key, Identification=key, Name=row["family"], Description=NOTICE,
                      IsMilestone=False, PredefinedType="NOTDEFINED")
        parents.append(parent)
        root("IfcRelNests", key, RelatingObject=parent, RelatedObjects=[tasks[item] for item in row["activity_ids"]])
    root("IfcRelAssignsToControl", "schedule", RelatingControl=work, RelatedObjects=parents)
    for edge in schedule["dependencies"]:
        left, right = edge["predecessor_id"], edge["successor_id"]
        require((edge["relation"], edge["lag_minutes"], edge["lag_basis"]) == ("FS", 0, "elapsed")
                and times[left][1] <= times[right][0], "Invalid controlled dependency.")
        root("IfcRelSequence", f"{left}/{right}", RelatingProcess=tasks[left], RelatedProcess=tasks[right],
             SequenceType="FINISH_START", Description=json.dumps(edge, sort_keys=True))

    target = folder / "scheduled.ifc"
    model.write(str(target))
    reopened = ifcopenshell.open(str(target))
    logger = json_logger()
    validate(reopened, logger)
    require(not logger.statements, f"IFC structural validation failed: {logger.statements[:2]}")
    require(all(str(reopened.by_id(key)) == value for key, value in original.items()),
            "Source IFC instances changed.")
    recovered = {}
    for task in reopened.by_type("IfcTask"):
        key = task.Identification
        if key in packages:
            require([item.Identification for rel in task.IsNestedBy for item in rel.RelatedObjects]
                    == packages[key]["activity_ids"], "Package membership changed.")
            continue
        time = task.TaskTime
        row = activities[key]
        links = [obj.GlobalId for rel in task.OperatesOn for obj in rel.RelatedObjects]
        require(links == [row["ifc_global_id"]] and
                _dates({"start": time.ScheduleStart, "finish": time.ScheduleFinish}) == times[key]
                and time.ActualStart is None and time.ActualFinish is None, "IFC task round trip failed.")
        recovered[key] = {"task_global_id": task.GlobalId, "element_global_id": links[0],
                          "work_package_id": row["work_package_id"]}
    require(recovered.keys() == activities.keys(), "Some activity identities are missing.")
    exported_edges = []
    for link in reopened.by_type("IfcRelSequence"):
        edge = json.loads(link.Description)
        require((edge["predecessor_id"], edge["successor_id"], "FINISH_START", None) ==
                (link.RelatingProcess.Identification, link.RelatedProcess.Identification,
                 link.SequenceType, link.TimeLag), "IFC dependency round trip failed.")
        exported_edges.append(edge)
    key = lambda edge: (edge["predecessor_id"], edge["successor_id"])
    require(sorted(exported_edges, key=key) == sorted(schedule["dependencies"], key=key),
            "Dependency coverage changed.")
    evidence = dict(status="PASS", original_instances_verified=len(original), activities=recovered,
                    dependencies=exported_edges, source_element_global_ids=sorted(elements),
                    provenance=metadata, restriction=NOTICE, output_ifc_sha256=_digest(target))
    for name, data in (("round_trip.json", evidence), ("viewer.json", build_viewer_data(schedule, evidence))):
        (folder / name).write_text(json.dumps(data, indent=2), encoding="utf-8")
