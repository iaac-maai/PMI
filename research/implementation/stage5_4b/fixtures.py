"""Adapters for the committed controlled references and frozen Stage 5.3A handover."""

import csv
from pathlib import Path

from pmi_core.scheduling.fixture import adapt, read_json, verify_reference


ROOT = Path(__file__).resolve().parents[3]
REFERENCES = ROOT / "research/validation/stage5_4a_independent_verification"
APPROVALS = ROOT / "research/validation/engineering_approval_review/priority_approval_register.csv"
R0_IDS = {
    "OF. 1ª ENCOFRADOR": "OF1_ENCOFRADOR",
    "PEÓN ESPECIAL": "PEON_ESPECIAL",
    "OF. 1ª FERRALLISTA": "OF1_FERRALLISTA",
    "OFICIAL 1ª": "OFICIAL_1",
}
REFERENCE_FIELDS = {
    "tick_minutes", "timezone", "project_start", "horizon_end", "project_calendar",
    "resources", "activities", "dependencies", "objective", "deadlines", "reservations",
    "inspection_pass_events", "strength_events",
}


def csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def approvals():
    original = csv_rows(APPROVALS)
    extra = csv_rows(REFERENCES / "engineering_approval_addendum.csv")
    rows = original + extra
    if (len(original), len(extra), len({row["approval_id"] for row in rows})) != (75, 13, 88):
        raise ValueError("Unexpected approval register identities or counts.")
    if any(row["status"] != "PENDING" for row in rows):
        raise ValueError("Controlled fixture requires all 88 approvals pending.")
    return rows


def reference_cases():
    originals = read_json(REFERENCES / "cpsat_reference_cases.json")["cases"]
    task7 = read_json(REFERENCES / "task7_reference_cases.json")["cases"]
    return {case["case_id"]: case for case in originals + [
        case for case in task7 if case["case_id"] != "RC06"]}


def remap(values):
    return {R0_IDS.get(name, name): value for name, value in values.items()}


def normalize_reference(case):
    """Translate the reference format explicitly, preserving all scheduling fields."""
    metadata = {"case_id", "category", "title", "expected", "notes", "source",
                "brute_force", "calendar_policy"}
    unknown = case.keys() - REFERENCE_FIELDS - metadata
    if unknown:
        raise ValueError(f"Unsupported reference fields: {sorted(unknown)}.")
    problem = {key: value for key, value in case.items() if key in REFERENCE_FIELDS}
    problem["scope"] = "hypothetical_fixture_only"
    problem["pending_approvals"] = approvals()
    zone = case["timezone"]
    resources = {}
    for name, source in case["resources"].items():
        rid = R0_IDS.get(name, name)
        resource = {"resource_id": rid, "display_name": name, "input_state": "hypothetical_fixture", **source}
        if isinstance(resource.get("calendar"), dict):
            resource["calendar"] = {"timezone": zone, **{k: v for k, v in resource["calendar"].items() if k != "note"}}
        if resource["kind"] == "reservation":
            resource.update(kind="reusable_asset", unit="set")
        elif resource.get("unit") == "m3/h":
            resource["kind"] = "supply_source"
        resources[rid] = resource
    problem["resources"] = resources
    if "deadlines" in problem:
        problem["deadlines"] = [{**row, "activity": "project" if row["activity"] == "PROJECT"
                                else row["activity"]} for row in problem["deadlines"]]
    problem["activities"] = [
        {**{k: v for k, v in task.items() if k != "derivation"}, "resources": remap(task["resources"])}
        for task in problem["activities"]]
    for task in problem["activities"]:
        if "split" in task:
            policy = task["split"]
            task["split"] = {k: v for k, v in policy.items() if k != "authorization"}
            task["split"].update(authorization_ref=policy["authorization"], retention_during_gap="release",
                                 restart_overhead_minutes=0, same_mode_on_restart=True, voluntary_pause=False)
    if case.get("reservations"):
        problem["reservations"] = [
            {"reservation_id": row["id"], "resource_id": row["resource"], "quantity": row["demand"],
             "occupancy_basis": "continuous_elapsed", "input_state": "hypothetical_fixture",
             "start_event": {"kind": "activity_start", "activity_id": row["from_activity"]},
             "release_condition": {
                 "all_of": [{"kind": "activity_finish", "activity_id": row["to_activity"]}],
                 "return_lead_minutes": 0, "reshoring": "not_permitted",
             },
             "covers_activities": [row["from_activity"], row["to_activity"]]}
            for row in case["reservations"]
        ]
    if case["case_id"] == "RC13b":
        problem["strength_events"] = [
            {**row, "acceptance_criterion_ref": "Task 7 hypothetical planned-test criterion"}
            for row in case["strength_events"]
        ]
    addendum = read_json(REFERENCES / "resource_contract_R2_addendum.json")
    if case["case_id"] == "RC06":
        exception, = addendum["R2-1_calendar_policy"]["exception"]["registered"]
        problem["calendar_exceptions"] = [{
            "exception_id": exception["exception_id"], "activity_ids": exception["activity_ids"],
            "replaces": exception["replaces"], "replacement_resource_id": "FERRALLISTA",
            "authorization_ref": exception["authorization_ref"], "input_state": "hypothetical_fixture",
        }]
    if case["case_id"] in {"R0-5", "R0-15"}:
        problem["fixture_exceptions"] = [entry for entry in addendum["R2-5_controlled_fixture_exceptions"]
                                         if entry["id"].startswith("FX-R0-")]
    return problem


def frozen_r0(tick):
    """Use 5.4A identities and FS edges, and preserve the 5.3A selected-mode inputs."""
    case = reference_cases()[f"R0-{tick}"]
    problem = normalize_reference(case)
    stage = ROOT / "research/implementation/stage5_4a"
    config = {**read_json(stage / "controlled_schedule_inputs.json"), "tick_minutes": tick}
    handover = read_json(ROOT / config["handover"])
    prep = ROOT / config["preparation_directory"]
    verify_reference(handover, prep, ROOT / config["fixture_inputs"])
    prepared = read_json(prep / "controlled_scheduling_inputs.json")
    baseline = adapt(handover, prepared, config)
    events = baseline["hypothetical_strength_events"]
    if set(events) != {"C-STRIKE", "B-STRIKE", "S-STRIKE"} or any(
        row["status"] != "hypothetical_pass_at_minimum" for row in events.values()
    ):
        raise ValueError("Unsupported R0 strength event. FX-R0-05 permits hypothetical passes at minimum only.")
    originals = {row["id"]: row for row in handover["activities"]}
    tasks = []
    for row in baseline["activities"]:
        uid = row["id"]
        kind = row["kind"]
        task = {
            "id": uid, "reference_id": row["reference_id"], "kind": (
                "elapsed_hold" if kind == "strength_release" else kind),
            "duration_minutes": row["duration_minutes"], "resources": remap(row["resources"]),
            "pending_approval_ids": row["pending_approval_ids"], "input_state": "hypothetical_fixture",
        }
        if row["allowed_hours"] is not None:
            task["allowed_hours"] = row["allowed_hours"]
        if kind == "productive":
            estimate = originals[uid]
            task.update(
                crew_mode=estimate["crew_id"], reference_cost_eur=estimate["reference_cost_eur"],
                positive_capacity=remap(estimate["worker_capacity_by_trade"] | estimate["equipment_capacity_by_class"]),
                demand_hours=remap(estimate["worker_hours_by_trade"] | estimate["machine_hours_by_class"]),
            )
            if row["reference_id"] == "C-POUR":
                task.update(reserved_without_bcca_demand={"OFICIAL_1": 1},
                            reservation_reason="Full HYP-CONC mode retains one official on the column pour.",
                            reservation_approval_ref="AP-X-CREW-01")
        tasks.append(task)
    problem.update(
        project_start=prepared["project"]["start_local"], horizon_end=config["horizon_local"],
        project_calendar={k: v for k, v in baseline["calendar"].items()
                          if k not in {"exception_note", "productive_phase_policy", "rounding", "utc_offset_jan"}}, activities=tasks, cost=baseline["cost"],
        cpm_baseline_minutes=baseline["makespan_elapsed_minutes"],
        dependencies=[{
            "predecessor": row["predecessor_id"], "successor": row["successor_id"],
            **{key: row[key] for key in ("relation", "lag_minutes", "lag_basis", "rule_id")},
        } for row in baseline["dependencies"]],
    )
    return problem

