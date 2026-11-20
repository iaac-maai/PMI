"""Versioned optimization result assembly."""
from pmi_core.scheduling.calendar import display
from .validation import validate

def serialize(problem, result, prepared, solver, starts, ends, pieces, reservation_ends, objective, bound, registry):
    zone, origin, _, tick, tasks, _, _, _, _, _, _, _, advanced = prepared
    _, _, conditional, blocked, reservations, _, _, _ = advanced
    for key, task in tasks.items():
        start, finish = [display(origin + solver.value(var) * tick, zone) for var in (starts[key], ends[key])]
        segments = [[display(origin + solver.value(a) * tick, zone), display(origin + solver.value(b) * tick, zone)]
                    for a, b, present, _ in pieces[key] if present is None or solver.boolean_value(present)]
        original = next(row for row in problem["activities"] if row["id"] == key)
        result["activities"].append({**original, "start": start, "finish": finish, "segments": segments})
    result["reservations"] = [
        {"reservation_id": key, "resource_id": rid, "quantity": units,
         "start": display(origin + solver.value(starts[start]) * tick, zone),
         "finish": display(origin + solver.value(reservation_ends[key]) * tick, zone)}
        for key, rid, units, start, *_ in reservations]
    result["conditional_activities"] = sorted(conditional & tasks.keys())
    result["blocked_activities"] = blocked
    if blocked:
        result.update(status="BLOCKED", solver_scope="unblocked_subset", diagnostic={"code": next(iter(blocked.values()))})
    elif result["conditional_activities"]:
        result.update(status="CONDITIONAL", solver_scope="conditional_projection", diagnostic={"code": "RELEASE_CONDITIONAL"})
    result["schedule_scope"] = ("unblocked_subset" if blocked else "conditional_projection"
                                if result["conditional_activities"] else "complete_project")
    result["makespan_by_scope_minutes"] = {result["schedule_scope"]: objective * tick}
    result["project_makespan_minutes"] = objective * tick if result["schedule_scope"] == "complete_project" else None
    result.update(objective_minutes=objective * tick, lower_bound_minutes=bound * tick,
                  optimality_gap_minutes=(objective - bound) * tick,
                  optimality_gap=(objective - bound) / max(1, abs(objective)),
                  completion_local=display(origin + objective * tick, zone))
    for key in ("cost", "fixture_exceptions", "cpm_baseline_minutes", "resources"):
        if key in problem:
            result[key] = problem[key]
    for key in ("inspection_pass_events", "strength_events", "release_events", "calendar_exceptions",
                "project_calendar", "dependencies"):
        if key in problem:
            result[key] = problem[key]
    result["reservation_declarations"] = problem.get("reservations", [])
    result.update(validate(problem, result, registry=registry))
    result["validated"] = True
    return result
