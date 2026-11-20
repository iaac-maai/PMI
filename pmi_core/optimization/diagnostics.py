"""Reservation witnesses and bounded infeasibility diagnostics."""
from collections import defaultdict
from datetime import datetime, timedelta

def deadline_scope(key, links, task_ids):
    """Return the activities subject to the deadline and their FS prerequisites."""
    if key == "project":
        return sorted(task_ids)
    predecessors = defaultdict(set)
    for left, right, _ in links:
        predecessors[right].add(left)
    visited, pending = set(), [key]
    while pending:
        activity = pending.pop()
        if activity not in visited:
            visited.add(activity)
            pending.extend(predecessors[activity])
    return sorted(visited)

def coverage_contradiction(reservations, links, durations):
    from .advanced import closure

    graph = [(left, right) for left, right, _ in links]
    contradictions = []
    for key, _, _, start, releases, lead, covered in reservations:
        for activity in covered:
            if activity != start and durations[activity] > 0 and start in closure([activity], graph):
                contradictions.append({"code": "STRUCTURAL_INFEASIBILITY", "cause": "RESERVATION_COVERAGE_PREDECESSOR",
                        "reservation_id": key, "covered_activity_id": activity, "start_activity_id": start})
            # C01 prohibits coverage of precedence successors of activity release events.
            if any(stamp is None and not delay and activity != endpoint
                   and activity in closure([endpoint], graph) for endpoint, _, stamp, delay in releases):
                contradictions.append({"code": "STRUCTURAL_INFEASIBILITY", "cause": "RESERVATION_COVERAGE_SUCCESSOR",
                        "reservation_id": key, "covered_activity_id": activity,
                        "release_activity_ids": sorted({event[0] for event in releases})})
    return {**contradictions[0], "contradictions": contradictions} if contradictions else None


def _without_deadline_diagnostic(problem, zone, origin, limit, budget, solve_probe):
    diagnostic = {"code": "INFEASIBLE", "cause": "UNDETERMINED",
                  "message": "No schedule fits the declared model and horizon."}
    if budget <= 0 or problem.get("deadlines") or any("latest_finish" in row for row in problem["activities"]):
        return diagnostic, 0.0
    try:
        extended = datetime.fromtimestamp(limit * 60, zone) + timedelta(days=14)
        candidate = {**problem, "horizon_end": extended.isoformat(timespec="minutes")}
        probe = solve_probe(candidate, min(budget, 1.0))
    except (OverflowError, OSError, ValueError):
        return diagnostic, 0.0
    diagnostic["extended_horizon_status"] = probe["status"]
    if probe["validated"] and origin + probe["objective_minutes"] > limit:
        diagnostic.update(code="HORIZON_EXHAUSTED", cause="VERIFIED_EXTENDED_HORIZON_SCHEDULE",
                          message="A validated schedule exists beyond the declared horizon.",
                          witness_completion=probe["completion_local"])
    return diagnostic, probe["runtime_seconds"]
