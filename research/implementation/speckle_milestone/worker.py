"""Schedule a qualified controlled handover with the existing CPM and CP-SAT engines."""
from copy import deepcopy
from math import isfinite

from pmi_core.optimization.engine import solve
from pmi_core.optimization.registry import ControlledRegistry
from pmi_core.schedule_result import schedule_result
from pmi_core.scheduling.cpm import calculate

STATE = "hypothetical_fixture"


def schedule_handover(handover, settings, *, source_sha256, approvals, project_id, provenance):
    """The caller is the trusted orchestrator and supplies the registered source and approvals."""
    if (handover["source_sha256"] != source_sha256
            or handover["scope"] != "hypothetical_fixture_only"
            or handover["eligible_for_controlled_scheduling_input"] is not True
            or handover["eligible_for_real_scheduling"] is not False):
        raise ValueError("Expected a qualified, registered hypothetical engineering handover.")
    if (len(approvals) != 88 or len({row["approval_id"] for row in approvals}) != 88
            or any(row["status"] != "PENDING" for row in approvals)):
        raise ValueError("Expected the 88 pending approvals.")
    rows = handover["activities"]
    if not rows or any(row["input_state"] != STATE or row["blockers"]
                       or row["eligible_for_real_scheduling"] is not False for row in rows):
        raise ValueError("Missing or unsupported engineering input.")
    calendar = {**settings["calendar"], "input_state": STATE}
    capacities = settings["resource_capacity"]
    resources = {
        key: {"resource_id": key, "display_name": key, "capacity": capacity,
              "kind": "renewable", "calendar": "project", "input_state": STATE,
              "evidence_ref": settings["evidence_ref"]}
        for key, capacity in capacities.items()
    }
    tasks, normalized = [], []
    for row in rows:
        kind = row["kind"]
        if kind not in {"productive", "elapsed_hold", "inspection"}:
            raise ValueError(f"Unsupported activity kind {kind}.")
        hours = row["elapsed_hours"] if kind == "elapsed_hold" else row["productive_hours"]
        if type(hours) not in (int, float) or not isfinite(hours) or hours <= 0:
            raise ValueError(f"Missing or invalid duration for {row['id']}.")
        demand = row["resource_demand"]
        if (kind != "elapsed_hold" and not demand) or (kind == "elapsed_hold" and demand):
            raise ValueError(f"Resource demand is incompatible with {row['id']}.")
        task = {"id": row["id"], "reference_id": row["work_item"], "kind": kind,
                "duration_minutes": hours * 60, "resources": demand,
                "reference_cost_eur": row["reference_cost_eur"],
                "pending_approval_ids": row["pending_approval_ids"]}
        normalized.append({**task, "input_state": STATE})
        tasks.append({**task, "global_id": row["global_id"], "package_id": row["package_id"],
                      "element_id": row["element_id"]})

    edges = handover["dependencies"]
    if any(edge["relation"] != "FS" or edge["lag_basis"] != "elapsed" for edge in edges):
        raise ValueError("Only finish-to-start elapsed dependencies are supported.")
    start, horizon, tick = (settings[key] for key in ("start", "horizon", "tick"))
    baseline = calculate(tasks, edges, calendar, start=start, horizon=horizon,
                         tick=tick, capacities=capacities)
    baseline.update({key: handover[key] for key in ("source_sha256", "model_version_id", "packages",
                                                   "element_quantities", "dependencies")})
    optimized = solve({
        "scope": "hypothetical_fixture_only", "timezone": calendar["timezone"], "tick_minutes": tick,
        "project_start": start, "horizon_end": horizon, "project_calendar": calendar,
        "resources": resources, "activities": normalized,
        "dependencies": [{"predecessor": e["predecessor_id"], "successor": e["successor_id"],
                          **{key: e[key] for key in ("relation", "lag_minutes", "lag_basis", "rule_id")}}
                         for e in edges],
        "cost": deepcopy(handover["cost"]), "cpm_baseline_minutes": baseline["makespan_elapsed_minutes"],
    }, registry=ControlledRegistry(tuple(approvals)))
    if (optimized["status"] != "OPTIMAL" or not optimized["validated"]
            or optimized["schedule_scope"] != "complete_project"):
        raise ValueError(f"Controlled schedule failed: {optimized['status']}.")
    return schedule_result(optimized=optimized, baseline=baseline, project_id=project_id,
                           provenance=provenance, engineering={row["id"]: row for row in rows})
