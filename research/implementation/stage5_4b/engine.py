"""Fixed-mode CP-SAT scheduling for controlled Stage 5.4B.1 inputs."""

from collections import defaultdict
from datetime import datetime
from graphlib import TopologicalSorter
from math import isfinite
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ortools.sat.python import cp_model

from pmi_core.scheduling.calendar import (
    SchedulingError, build_windows, display, parse_minute, round_duration,
)


INFEASIBLE = {"IMPOSSIBLE_CREW", "NO_FIT", "INFEASIBLE_DEADLINE"}
DEFERRED = {
    "reservations", "release_events", "inspection_pass_events", "strength_events",
    "hypothetical_strength_events", "supply_sources", "pour_supply_demands",
    "split_policies", "events",
}


def require(condition, message, code="MODEL_INVALID", **details):
    if not condition:
        raise SchedulingError(code, message, **details)


def supported(data, allowed):
    extra = data.keys() - allowed
    require(not extra, f"Unsupported fields: {sorted(extra)}.", "UNSUPPORTED_CONSTRAINT")


def integer(value, minimum=0):
    return type(value) is int and minimum <= value < 2**31


def available(calendar, origin, limit, tick):
    supported(calendar, {"timezone", "working_windows", "date_exceptions", "date_overrides",
                         "tick_minutes", "input_state"})
    return build_windows(calendar, origin, limit, tick)


def prepare(problem):
    """Validate the normalized controlled input and build individual start domains."""
    require(problem["scope"] == "hypothetical_fixture_only", "Controlled inputs only.")
    require(problem.get("objective", "minimize_makespan") == "minimize_makespan",
            "Unsupported objective.", "UNSUPPORTED_CONSTRAINT")
    for key in sorted(DEFERRED & problem.keys()):
        require(not problem[key], f"{key} requires Stage 5.4B.2.", "UNSUPPORTED_CONSTRAINT")
    supported(problem, DEFERRED | {
        "scope", "objective", "timezone", "tick_minutes", "project_start", "horizon_end",
        "project_calendar", "calendar_exceptions", "resources", "activities", "dependencies",
        "deadlines", "fixture_exceptions", "pending_approvals", "cost", "cpm_baseline_minutes",
    })
    tick = problem.get("tick_minutes", 5)
    require(integer(tick, 1) and 60 % tick == 0, "Tick must divide 60.", "TICK_MISALIGNED")
    zone = ZoneInfo(problem["timezone"])
    origin = parse_minute(problem["project_start"], zone, tick)
    limit = parse_minute(problem["horizon_end"], zone, tick, upper=True)
    require(origin < limit, "Horizon must follow project start.")
    project = problem["project_calendar"]
    require(project["timezone"] == zone.key, "Project timezones must agree.")
    project_windows = available(project, origin, limit, tick)
    tasks = {}
    for task in problem["activities"]:
        key = task["id"]
        require(isinstance(key, str) and key and key not in tasks and key != "project",
                "Invalid, reserved or duplicate activity ID.")
        tasks[key] = task
    require(tasks, "Provide at least one activity.")
    capacities, resource_windows = {}, {}
    for key, resource in problem["resources"].items():
        supported(resource, {"resource_id", "display_name", "capacity", "calendar", "kind",
                             "unit", "explicit_none", "input_state", "approval_ref"})
        require(re.fullmatch(r"[A-Z0-9_][A-Z0-9_.-]*", key) and resource["resource_id"] == key,
                f"Invalid resource identity: {key}.")
        require(isinstance(resource["display_name"], str) and resource["display_name"].strip(),
                f"Missing display name for {key}.", "MISSING_INPUT")
        require(resource["kind"] in {"renewable", "labour_trade", "equipment", "inspector"}
                and resource.get("unit") != "m3/h",
                f"Unsupported resource type for {key}.", "UNSUPPORTED_CONSTRAINT")
        capacity = resource["capacity"]
        require(capacity is not None and resource.get("input_state") != "missing",
                f"Missing capacity for {key}.", "MISSING_INPUT")
        require(integer(capacity), f"Invalid capacity for {key}.")
        require(not resource.get("explicit_none") or capacity == 0, f"Invalid explicit none for {key}.")
        calendar = resource["calendar"]
        require(calendar is not None, f"Missing calendar for {key}.", "MISSING_INPUT")
        if calendar == "project":
            resource_windows[key] = project_windows
        else:
            resource_windows[key] = available(calendar, origin, limit, tick)
        capacities[key] = capacity
    replacements = {}
    exception_ids = set()
    for entry in problem.get("calendar_exceptions", []):
        supported(entry, {"exception_id", "activity_ids", "resource_id", "replaces",
                          "replacement_resource_id", "authorization_ref", "input_state"})
        authorization = entry.get("authorization_ref")
        if not isinstance(authorization, str) or not authorization.strip():
            continue
        rid = entry["replacement_resource_id"]
        require(entry["exception_id"] and entry["exception_id"] not in exception_ids
                and entry["input_state"] == "hypothetical_fixture"
                and entry["replaces"] == "project_calendar" and rid in capacities,
                "Invalid calendar exception.")
        exception_ids.add(entry["exception_id"])
        selected = entry.get("activity_ids")
        if selected is None:
            scoped_resource = entry["resource_id"]
            require(scoped_resource in capacities, "Unknown exception scope resource.")
            selected = [key for key, row in tasks.items() if scoped_resource in row["resources"]]
        require(selected, "Calendar exception must name affected activities.")
        for key in selected:
            require(key in tasks and key not in replacements, f"Invalid calendar exception scope: {key}.")
            replacements[key] = resource_windows[rid]

    domains, durations, occupancy = {}, {}, {}
    for key, task in tasks.items():
        supported(task, {"id", "kind", "duration_minutes", "resources", "allowed_hours", "interruption",
                         "split", "not_before", "latest_finish", "reference_id", "crew_mode",
                         "reference_cost_eur", "positive_capacity", "demand_hours",
                         "reserved_without_bcca_demand", "reservation_reason", "reservation_approval_ref",
                         "pending_approval_ids", "input_state", "required_equipment"})
        require(task.get("input_state") != "missing", f"Missing inputs for {key}.", "MISSING_INPUT")
        interruption = task.get("interruption", "non_interruptible")
        if interruption == "split_allowed":
            policy = task.get("split", {})
            require((policy.get("authorization_ref") or policy.get("authorization"))
                    and policy.get("max_segments") and policy.get("min_segment_minutes"),
                    f"Missing split authorization or rules for {key}.", "SPLIT_NOT_AUTHORIZED")
        require(interruption == "non_interruptible" and not task.get("split"),
                f"Unsupported interruption for {key}.", "UNSUPPORTED_CONSTRAINT")
        kind = task["kind"]
        require(kind in {"productive", "inspection", "elapsed_hold", "milestone"},
                f"Unsupported activity kind for {key}: {kind}.", "UNSUPPORTED_CONSTRAINT")
        demand = task["resources"]
        elapsed = kind in {"elapsed_hold", "milestone"}
        require(not elapsed or (not demand and task.get("allowed_hours") is None),
                f"Elapsed activity {key} may not demand working resources or windows.")
        if kind != "productive":
            require(task.get("reference_cost_eur") in (None, 0), f"Unexpected cost for {key}.")
        duration = round_duration(task["duration_minutes"], tick)
        require((duration == 0) == (kind == "milestone"), f"Invalid duration for {key}.")
        for rid in task.get("required_equipment", []):
            require(rid in capacities, f"Missing required equipment declaration for {key}: {rid}.",
                    "EXPLICIT_NONE_REQUIRED")
        if "crew_mode" in task:
            require(task["crew_mode"], f"Missing mode for {key}.", "MISSING_INPUT")
            positive = task["positive_capacity"]
            reserved = task.get("reserved_without_bcca_demand", {})
            require(not positive.keys() & reserved.keys() and demand == (positive | reserved)
                    and all(integer(units, 1) for units in [*positive.values(), *reserved.values()])
                    and (not reserved or (task.get("reservation_reason") and task.get("reservation_approval_ref"))),
                    f"Selected mode occupancy mismatch for {key}.", "MODE_MISMATCH")
            hours = task["demand_hours"]
            require(hours.keys() == positive.keys() and all(
                type(value) in (int, float) and 0 < value <= positive[rid] * duration / 60 + 1e-9
                for rid, value in hours.items()), f"Selected mode has insufficient reserved hours for {key}.")
        calendars = [] if elapsed else [replacements.get(key, project_windows)]
        if task.get("allowed_hours") is not None:
            restriction = {"timezone": zone.key, "working_windows": [
                {"weekday": day, "start": left, "end": right}
                for day in range(1, 8) for left, right in task["allowed_hours"]]}
            calendars.append(available(restriction, origin, limit, tick))
        for rid, units in demand.items():
            require(rid in capacities, f"{key} demands undeclared resource {rid}.", "MISSING_INPUT")
            require(integer(units, 1), f"Invalid demand for {key}: {rid}.")
            require(units <= capacities[rid], f"{key} needs {units} {rid}; capacity is {capacities[rid]}.",
                    "IMPOSSIBLE_CREW", activity_id=key, resource_id=rid)
            calendars.append(resource_windows[rid])
        windows = [(origin, limit)]
        for calendar in calendars:
            windows = [(max(a, c), min(b, d)) for a, b in windows for c, d in calendar
                       if max(a, c) < min(b, d)]
        release = parse_minute(task["not_before"], zone, tick) if "not_before" in task else origin
        domains[key] = [((max(a, release) - origin) // tick, (b - duration - origin) // tick)
                        for a, b in windows if max(a, release) + duration <= b]
        require(domains[key], f"No uninterrupted window fits {key}.", "NO_FIT", activity_id=key)
        durations[key] = duration // tick
        occupancy[key] = calendars

    graph = {key: set() for key in tasks}
    links = []
    for edge in problem["dependencies"]:
        supported(edge, {"predecessor", "successor", "relation", "lag_minutes", "lag_basis", "rule_id"})
        left, right = edge["predecessor"], edge["successor"]
        require(left in tasks and right in tasks, "Unknown dependency endpoint.")
        lag = edge["lag_minutes"]
        require(edge["relation"] == "FS" and edge["lag_basis"] == "elapsed"
                and type(lag) in (int, float) and lag >= 0,
                f"Unsupported dependency {left} → {right}.", "UNSUPPORTED_RELATION")
        links.append((left, right, round_duration(lag, tick) // tick))
        graph[right].add(left)
    order = list(TopologicalSorter(graph).static_order())
    deadlines = []
    for row in problem.get("deadlines", []):
        supported(row, {"activity", "latest_finish"})
        key = row["activity"]
        require(key == "project" or key in tasks, f"Unknown deadline endpoint: {key}.")
        deadlines.append((key, parse_minute(row["latest_finish"], zone, tick, upper=True)))
    deadlines.extend((key, parse_minute(task["latest_finish"], zone, tick, upper=True))
                     for key, task in tasks.items() if "latest_finish" in task)
    # Earliest calendar/precedence finish is a valid lower bound even with shared capacity.
    early = {}
    for key in order:
        bound = max((early[a] + lag for a, b, lag in links if b == key), default=0)
        start = next((max(lo, bound) for lo, hi in domains[key] if hi >= bound), None)
        require(start is not None, f"Precedence leaves no window for {key}.", "NO_FIT", activity_id=key)
        early[key] = start + durations[key]
    for key, deadline in deadlines:
        earliest = max(early.values()) if key == "project" else early[key]
        require(origin + earliest * tick <= deadline, f"Deadline for {key} precedes its earliest finish.",
                "INFEASIBLE_DEADLINE", activity_id=key, latest_finish=display(deadline, zone),
                prerequisite_ids=deadline_scope(key, links, tasks))
    return (zone, origin, limit, tick, tasks, capacities, domains, durations, occupancy,
            links, deadlines, max(early.values()))


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


def validate(problem, result):
    """Reparse returned timestamps and check feasibility without CP-SAT variables."""
    (zone, origin, limit, tick, tasks, capacities, _, durations, calendars,
     links, deadlines, _) = prepare(problem)
    spans, usage = {}, defaultdict(lambda: defaultdict(int))
    for row in result["activities"]:
        key = row["id"]
        require(key in tasks and key not in spans, f"Unexpected or duplicate scheduled activity: {key}.")
        values = [datetime.fromisoformat(row[name]) for name in ("start", "finish")]
        require(all(value.tzinfo is not None for value in values), f"Missing timestamp offset for {key}.")
        a, b = [value.timestamp() / 60 for value in values]
        require(origin <= a <= b <= limit and not (a - origin) % tick and not (b - origin) % tick,
                f"Off-grid or out-of-horizon schedule for {key}.")
        require(b - a == durations[key] * tick and row["segments"] == [[row["start"], row["finish"]]],
                f"Unexpected duration or segments for {key}.")
        task = tasks[key]
        if "not_before" in task:
            require(a >= parse_minute(task["not_before"], zone, tick), f"Early start for {key}.")
        require(all(any(left <= a and b <= right for left, right in windows) for windows in calendars[key]),
                f"Calendar violation for {key}.")
        for rid, units in task["resources"].items():
            usage[rid][a] += units
            usage[rid][b] -= units
        spans[key] = a, b
    require(spans.keys() == tasks.keys(), "Incomplete schedule.")
    for rid, events in usage.items():
        load = 0
        for minute in sorted(events):
            load += events[minute]
            require(load <= capacities[rid], f"Overcapacity for {rid} at {display(minute, zone)}.")
    for left, right, lag in links:
        require(spans[left][1] + lag * tick <= spans[right][0], f"Precedence violation: {left} → {right}.")
    finish = max(end for _, end in spans.values())
    for key, deadline in deadlines:
        require((finish if key == "project" else spans[key][1]) <= deadline, f"Missed deadline for {key}.")
    require(result["objective_minutes"] == finish - origin
            and result["completion_local"] == display(finish, zone), "Makespan mismatch.")


def solve(problem, *, time_limit=10.0):
    """Return a verified controlled schedule or a structured diagnostic."""
    result = {"solver_status": None, "objective_minutes": None, "lower_bound_minutes": None,
              "optimality_gap": None, "runtime_seconds": 0.0, "real_project_eligible": False,
              "activities": [], "validated": False}
    try:
        require(isfinite(time_limit) and time_limit > 0, "Time limit must be positive.")
        prepared = prepare(problem)
    except SchedulingError as error:
        return dict(result, status="INFEASIBLE" if error.code in INFEASIBLE else "MODEL_INVALID",
                    diagnostic={"code": error.code, "message": str(error), **error.details})
    except (KeyError, TypeError, ValueError, AttributeError, ZoneInfoNotFoundError, OverflowError) as error:
        return dict(result, status="MODEL_INVALID",
                    diagnostic={"code": "MISSING_INPUT" if isinstance(error, KeyError) else "MODEL_INVALID",
                                "message": str(error)})
    (zone, origin, limit, tick, tasks, capacities, domains, durations, _,
     links, deadlines, lower) = prepared
    model = cp_model.CpModel()
    horizon = (limit - origin) // tick
    starts, ends = {}, {}
    intervals, demands = defaultdict(list), defaultdict(list)
    for key, task in tasks.items():
        starts[key] = model.new_int_var_from_domain(cp_model.Domain.from_intervals(domains[key]), f"start:{key}")
        ends[key] = model.new_int_var(0, horizon, f"finish:{key}")
        interval = model.new_interval_var(starts[key], durations[key], ends[key], key)
        for rid, units in task["resources"].items():
            intervals[rid].append(interval)
            demands[rid].append(units)
    for rid in intervals:
        model.add_cumulative(intervals[rid], demands[rid], capacities[rid])
    for left, right, lag in links:
        model.add(starts[right] >= ends[left] + lag)
    makespan = model.new_int_var(lower, horizon, "makespan")
    model.add_max_equality(makespan, list(ends.values()))
    labels = {}
    for key, deadline in deadlines:
        label = model.new_bool_var(f"deadline:{key}:{deadline}")
        model.add((makespan if key == "project" else ends[key]) <= (deadline - origin) // tick).only_enforce_if(label)
        model.add_assumption(label)
        labels[label.index] = {"activity_id": key, "latest_finish": display(deadline, zone),
                               "prerequisite_ids": deadline_scope(key, links, tasks)}
    model.minimize(makespan)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 1
    status = solver.solve(model)
    runtime = solver.wall_time
    result.update(status=solver.status_name(status), solver_status=solver.status_name(status),
                  runtime_seconds=runtime)
    if status == cp_model.INFEASIBLE:
        core = [labels[index] for index in solver.sufficient_assumptions_for_infeasibility()]
        if core:
            # A core need not be minimal and can contain deadlines even if the base is infeasible.
            model.clear_assumptions()
            check = cp_model.CpSolver()
            check.parameters.max_time_in_seconds = max(0.001, time_limit - runtime)
            base = check.solve(model)
            result["runtime_seconds"] += check.wall_time
            if base in (cp_model.FEASIBLE, cp_model.OPTIMAL):
                result["diagnostic"] = {"code": "INFEASIBLE_DEADLINE", "deadlines": core}
            else:
                result["diagnostic"] = {"code": "INFEASIBLE", "deadline_candidates": core,
                                        "without_deadlines_status": check.status_name(base)}
        return result
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if status == cp_model.UNKNOWN:
            result["lower_bound_minutes"] = max(lower, solver.best_objective_bound) * tick
        return result
    objective = solver.value(makespan)
    bound = max(lower, solver.best_objective_bound)
    # Choose early dates within the proven makespan, using only the remaining solve budget.
    if status == cp_model.OPTIMAL and time_limit > runtime:
        model.add(makespan == objective)
        model.minimize(sum(starts.values()))
        tie_break = cp_model.CpSolver()
        tie_break.parameters.num_search_workers = 1
        tie_break.parameters.max_time_in_seconds = time_limit - runtime
        tie_status = tie_break.solve(model)
        result["runtime_seconds"] += tie_break.wall_time
        if tie_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            solver = tie_break
    for key, task in tasks.items():
        start, finish = [display(origin + solver.value(var) * tick, zone) for var in (starts[key], ends[key])]
        result["activities"].append({**task, "start": start, "finish": finish, "segments": [[start, finish]]})
    result.update(objective_minutes=objective * tick, lower_bound_minutes=bound * tick,
                  optimality_gap=(objective - bound) / max(1, abs(objective)),
                  completion_local=display(origin + objective * tick, zone))
    for key in ("cost", "pending_approvals", "fixture_exceptions", "cpm_baseline_minutes", "resources"):
        if key in problem:
            result[key] = problem[key]
    validate(problem, result)
    result["validated"] = True
    return result

