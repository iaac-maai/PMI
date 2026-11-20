"""Application schedule result contract, independent of the solver runtime."""
from datetime import datetime


def _elapsed(start, finish):
    return int((datetime.fromisoformat(finish) - datetime.fromisoformat(start)).total_seconds() // 60)


def schedule_result(*, optimized, baseline=None, project_id=None, provenance=None, engineering=None, activity_metadata=None):
    """Join stable activity IDs across CPM and optimization. Missing model links remain null."""
    baseline = baseline or {}
    engineering = engineering or {}
    activity_metadata = activity_metadata or {}
    early = {row["id"]: row for row in baseline.get("activities", [])}
    chosen = {row["id"]: row for row in optimized.get("activities", [])}
    activities = []
    for key in dict.fromkeys([*early, *chosen]):
        source, solution = early.get(key, {}), chosen.get(key)
        start = solution["start"] if solution else None
        finish = solution["finish"] if solution else None
        segments = solution["segments"] if solution else []
        kind = source.get("kind") or (solution or {}).get("kind")
        estimate = engineering.get(key, {})
        context = activity_metadata.get(key, {})
        activities.append({
            "activity_id": key, "reference_id": source.get("reference_id"),
            "ifc_global_id": source.get("global_id"), "canonical_element_id": source.get("element_id"),
            "work_package_id": source.get("package_id") or context.get("package_id"), "kind": kind,
            "baseline": ({"start": source["earliest_start"], "finish": source["earliest_finish"],
                          "late_start": source["latest_start"], "late_finish": source["latest_finish"],
                          "working_minutes": source["scheduled_minutes"] if kind in {"productive", "inspection"} else 0,
                          "elapsed_minutes": _elapsed(source["earliest_start"], source["earliest_finish"]),
                          "cpm_critical": source["critical"]} if source else None),
            "optimized": ({"start": start, "finish": finish, "segments": segments,
                           "working_minutes": sum(_elapsed(a, b) for a, b in segments)
                           if kind in {"productive", "inspection"} else 0,
                           "elapsed_minutes": _elapsed(start, finish)} if solution else None),
            "input_state": (solution or {}).get("input_state"),
            "approval_ids": (solution or source).get("pending_approval_ids", []),
            "direct_reference_cost_eur": (solution or source).get("reference_cost_eur"),
            "engineering_quantity": ({"value": estimate.get("quantity"), "unit": estimate.get("unit"),
                                       "state": estimate.get("input_state"),
                                       "evidence_ids": estimate.get("quantity_ids", [])} if estimate else None),
            "evidence_ref": (solution or {}).get("evidence_ref") or estimate.get("assumption_ref"),
            "selected_mode": (solution or {}).get("crew_mode"),
        })
    proof_fields = ("status", "solver_status", "solver_scope", "schedule_scope",
                    "project_makespan_minutes", "makespan_by_scope_minutes", "lower_bound_minutes",
                    "optimality_gap", "optimality_gap_minutes", "timestamp_source", "runtime_seconds",
                    "primary_runtime_seconds", "secondary_runtime_seconds", "diagnostic_runtime_seconds")
    return {
        "contract_version": "pmi-schedule/1", "project_id": project_id,
        "model_version_id": baseline.get("model_version_id"), "source_ifc_sha256": baseline.get("source_sha256"),
        "activities": activities, "work_packages": baseline.get("packages", []),
        "element_quantities": baseline.get("element_quantities", []),
        "dependencies": baseline.get("dependencies", optimized.get("dependencies", [])),
        "cpm": {"critical_activity_ids": baseline.get("critical_activity_ids", []),
                "critical_edges": baseline.get("critical_edges", []),
                "makespan_minutes": baseline.get("makespan_elapsed_minutes")},
        "proof": {key: optimized.get(key) for key in proof_fields},
        "diagnostic": optimized.get("diagnostic"), "internal_timestamp_validated": optimized["validated"],
        "blocked_activities": optimized.get("blocked_activities", {}),
        "conditional_activities": optimized.get("conditional_activities", []),
        "reservations": optimized.get("reservations", []),
        "reservation_declarations": optimized.get("reservation_declarations", []),
        "resource_occupancy": optimized.get("resource_occupancy", []),
        "resource_conflicts": optimized.get("resource_conflicts", []),
        "resource_input": optimized.get("resources", {}),
        "supply": {key: optimized.get(key) for key in
                   ("supply_by_activity", "supply_by_source", "supply_checks", "supply_totals")},
        "cost": {"scope": "direct_reference_only", **optimized.get("cost", {})},
        "pending_approvals": optimized.get("pending_approvals", []),
        "fixture_exceptions": optimized.get("fixture_exceptions", []),
        "events": {key: optimized.get(key) for key in ("inspection_pass_events", "strength_events", "release_events")},
        "evidence": provenance or {}, "real_project_eligible": False,
    }
