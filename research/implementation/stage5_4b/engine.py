"""Fixed-mode CP-SAT scheduling for controlled Stage 5.4B.1 inputs."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from fractions import Fraction
from graphlib import TopologicalSorter
from math import ceil, isfinite
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ortools.sat.python import cp_model

from pmi_core.scheduling.calendar import (
    SchedulingError, build_windows, display, parse_minute, round_duration,
)


INFEASIBLE = {"IMPOSSIBLE_CREW", "NO_FIT", "INFEASIBLE_DEADLINE", "HORIZON_EXHAUSTED"}
DEFERRED = {
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
                         "tick_minutes", "input_state", "evidence_ref"})
    for row in calendar["working_windows"]:
        supported(row, {"weekday", "start", "end"})
    exceptions = calendar.get("date_exceptions", [])
    overrides = calendar.get("date_overrides", {})
    require(len(exceptions) == len(set(exceptions)), "Duplicate calendar date exceptions.")
    for label in [*exceptions, *overrides]:
        require(date.fromisoformat(label).isoformat() == label, f"Non-ISO calendar date: {label!r}.")
    for rows in overrides.values():
        for row in rows:
            supported(row, {"start", "end"})
    return build_windows(calendar, origin, limit, tick)


def prepare(problem, *, ignored_exceptions=None):
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
        "reservations", "strength_events", "inspection_pass_events", "release_events",
    })
    from .advanced import normalize, split_policy
    from .capacity_dates import capacity_periods
    from .input_states import audit_input_states
    from .controlled_metadata import calendar_exception_reason

    tick = problem.get("tick_minutes", 5)
    require(integer(tick, 1) and 60 % tick == 0, "Tick must divide 60.", "TICK_MISALIGNED")
    zone = ZoneInfo(problem["timezone"])
    origin = parse_minute(problem["project_start"], zone, tick)
    limit = parse_minute(problem["horizon_end"], zone, tick, upper=True)
    require(origin < limit, "Horizon must follow project start.")
    audit_input_states(problem, require)
    ids = [task["id"] for task in problem["activities"]]
    require(all(isinstance(key, str) and key and key != "project" for key in ids)
            and len(set(ids)) == len(ids), "Invalid, reserved or duplicate activity ID.")
    for task in problem["activities"]:
        key = task["id"]
        supported(task, {"id", "kind", "duration_minutes", "resources", "allowed_hours", "interruption",
                         "split", "not_before", "latest_finish", "reference_id", "crew_mode",
                         "reference_cost_eur", "positive_capacity", "demand_hours",
                         "reserved_without_bcca_demand", "reservation_reason", "reservation_approval_ref",
                         "pending_approval_ids", "input_state", "required_equipment", "explicit_none_equipment", "is_pour",
                         "crew_mode_input_state", "evidence_ref"})
        mode_fields = {"positive_capacity", "demand_hours", "reserved_without_bcca_demand",
                       "reservation_reason", "reservation_approval_ref", "crew_mode_input_state"}
        require("crew_mode" in task or not mode_fields & task.keys(),
                f"Crew-mode fields without a selected mode on {key}.", "MODE_MISMATCH")
        for rid in task["resources"]:
            require(not problem["resources"].get(rid, {}).get("explicit_none"),
                    f"{key} demands {rid}, which is declared explicitly unused.", "MISSING_INPUT",
                    activity_id=key, resource_id=rid)
    known_ids = set(ids)
    for edge in problem["dependencies"]:
        supported(edge, {"predecessor", "successor", "relation", "lag_minutes", "lag_basis", "rule_id"})
        left, right = edge["predecessor"], edge["successor"]
        require(left in known_ids and right in known_ids, "Unknown dependency endpoint.")
        lag = edge["lag_minutes"]
        require(edge["relation"] == "FS" and edge["lag_basis"] == "elapsed"
                and type(lag) in (int, float) and isfinite(lag) and lag >= 0,
                f"Unsupported dependency {left} ? {right}.", "UNSUPPORTED_RELATION")
    exception_input = problem
    problem, recorded, strength, conditional, blocked, reservations, supplies = normalize(problem, zone, tick)
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
    capacities, resource_windows, profiles = {}, {}, {}
    tail = max((lead + max(delay for _, _, _, delay in releases)
                for _, _, _, _, releases, lead, _ in reservations), default=0) * tick
    for key, resource in problem["resources"].items():
        supported(resource, {"resource_id", "display_name", "capacity", "calendar", "kind",
                             "unit", "explicit_none", "input_state", "approval_ref", "max_volume_per_day_m3",
                             "capacity_by_date", "evidence_ref"})
        require(re.fullmatch(r"[A-Z0-9_][A-Z0-9_.-]*", key) and resource["resource_id"] == key,
                f"Invalid resource identity: {key}.")
        require(isinstance(resource["display_name"], str) and resource["display_name"].strip(),
                f"Missing display name for {key}.", "MISSING_INPUT")
        require(resource["kind"] in {"renewable", "labour_trade", "equipment", "inspector", "reusable_asset",
                                     "supply_source"} and
                (resource.get("unit") != "m3/h" or resource["kind"] == "supply_source"),
                f"Unsupported resource type for {key}.", "UNSUPPORTED_CONSTRAINT")
        capacity = resource["capacity"]
        require(capacity is not None and resource.get("input_state") != "missing",
                f"Missing capacity for {key}.", "MISSING_INPUT")
        require(integer(capacity), f"Invalid capacity for {key}.")
        require(type(resource.get("explicit_none", False)) is bool and
                (not resource.get("explicit_none") or capacity == 0),
                f"Invalid explicit none for {key}.", "MISSING_INPUT")
        calendar = resource["calendar"]
        require(calendar is not None, f"Missing calendar for {key}.", "MISSING_INPUT")
        scale = supplies[key][0] if key in supplies else 1
        bound = limit + tail if resource["kind"] == "reusable_asset" else limit
        profiles[key] = capacity_periods(resource, capacity, scale, zone, origin, bound, tick)
        capacities[key] = max(value for _, _, value in profiles[key])
        if resource["kind"] == "reusable_asset":
            require(calendar == "continuous" and resource.get("unit") in {"set", "piece", "panel"},
                    f"Reusable resource {key} needs explicit physical units and continuous availability.")
            continue
        require(calendar != "continuous", f"Resource {key} requires a working calendar.")
        if calendar == "project":
            resource_windows[key] = project_windows
        else:
            resource_windows[key] = available(calendar, origin, limit, tick)
    for reservation, rid, quantity, *_ in reservations:
        require(not problem["resources"][rid].get("explicit_none"),
                f"Reservation {reservation} demands explicitly unused resource {rid}.", "MISSING_INPUT")
        require(quantity <= capacities[rid], f"Insufficient physical capacity for {reservation}.",
                "IMPOSSIBLE_CREW")
    replacements = {}
    exception_ids = set()
    for entry in problem.get("calendar_exceptions", []):
        supported(entry, {"exception_id", "activity_ids", "resource_id", "replaces",
                          "replacement_resource_id", "authorization_ref", "input_state"})
        reason = calendar_exception_reason(exception_input, entry)
        if reason:
            if ignored_exceptions is not None:
                ignored_exceptions.append({"exception_id": entry.get("exception_id"), "reason": reason})
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

    domains, durations, occupancy, splits = {}, {}, {}, {}
    for key, task in tasks.items():
        require(task.get("input_state") != "missing", f"Missing inputs for {key}.", "MISSING_INPUT")
        policy = split_policy(task, tick)
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
        for rid in task.get("explicit_none_equipment", []):
            require(rid in capacities and problem["resources"][rid].get("explicit_none") is True,
                    f"Missing explicit-none equipment declaration for {key}: {rid}.",
                    "EXPLICIT_NONE_REQUIRED")
        if "crew_mode" in task:
            require(isinstance(task["crew_mode"], str) and task["crew_mode"].strip(),
                    f"Missing mode for {key}.", "MISSING_INPUT")
            positive = task["positive_capacity"]
            reserved = task.get("reserved_without_bcca_demand", {})
            working = {rid: units for rid, units in demand.items() if rid not in supplies}
            require(not positive.keys() & reserved.keys() and working == (positive | reserved)
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
            require(rid in resource_windows and integer(units, 1), f"Invalid working demand for {key}: {rid}.")
            require(units <= capacities[rid], f"{key} needs {units} {rid}; capacity is {capacities[rid]}.",
                    "IMPOSSIBLE_CREW", activity_id=key, resource_id=rid, mode_code="NO_ELIGIBLE_MODE")
            calendars.append(resource_windows[rid])
        windows = [(origin, limit)]
        for calendar in calendars:
            windows = [(max(a, c), min(b, d)) for a, b in windows for c, d in calendar
                       if max(a, c) < min(b, d)]
        release = parse_minute(task["not_before"], zone, tick) if "not_before" in task else origin
        minimum = policy[1] * tick if policy else duration
        domains[key] = [((max(a, release) - origin) // tick, (b - minimum - origin) // tick)
                        for a, b in windows if max(a, release) + minimum <= b]
        require(domains[key], f"No uninterrupted window fits {key}.", "NO_FIT", activity_id=key)
        if policy:
            splits[key] = policy, [((max(a, release) - origin) // tick, (b - origin) // tick)
                                   for a, b in windows if b > max(a, release)]
        durations[key] = duration // tick
        occupancy[key] = calendars

    graph = {key: set() for key in tasks}
    links = []
    for edge in problem["dependencies"]:
        left, right = edge["predecessor"], edge["successor"]
        lag = edge["lag_minutes"]
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
        if key in strength:
            pour, minimum, fixed = strength[key]
            early[key] = max(early[pour] + round_duration(minimum, tick) // tick,
                             (fixed - origin) // tick if fixed is not None else 0)
        if key in recorded:
            require(origin + early[key] * tick <= recorded[key],
                    f"Recorded pass before earliest activity finish for {key}.",
                    "EVENT_BEFORE_ACTIVITY_FINISH", activity_id=key)
    for key, deadline in deadlines:
        earliest = max(early.values()) if key == "project" else early[key]
        require(origin + earliest * tick <= deadline, f"Deadline for {key} precedes its earliest finish.",
                "INFEASIBLE_DEADLINE", activity_id=key, latest_finish=display(deadline, zone),
                prerequisite_ids=deadline_scope(key, links, tasks))
    require(origin + max(early.values()) * tick <= limit,
            "The calendar and precedence lower bound exceeds the declared horizon.",
            "HORIZON_EXHAUSTED", cause="PRECEDENCE_LOWER_BOUND")
    return (zone, origin, limit, tick, tasks, capacities, domains, durations, occupancy,
            links, deadlines, max(early.values()),
            (recorded, strength, conditional, blocked, reservations, supplies, splits, profiles))


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
    """Recheck timestamps without CP-SAT variables using the model's shared input preparation.

    Calendar expansion and event normalization are shared. External acceptance uses
    the separate Agent 2 oracle on the source fixtures.
    """
    (zone, origin, limit, tick, tasks, capacities, _, durations, calendars,
     links, deadlines, _, advanced) = prepare(problem)
    recorded, strength, conditional, blocked, reservations, supplies, splits, profiles = advanced
    from .advanced import local_days
    spans, segment_map, usage = {}, {}, defaultdict(lambda: defaultdict(int))
    ledger, supply_checks = [], []

    def occupy(rid, units, a, b, holder, basis):
        usage[rid][a] += units
        usage[rid][b] -= units
        scale = supplies[rid][0] if rid in supplies else 1
        ledger.append({"resource_id": rid, "holder_id": holder, "occupancy_basis": basis,
                       "demand": units if scale == 1 else units / scale,
                       "unit": problem["resources"][rid].get("unit"),
                       "start": display(a, zone), "finish": display(b, zone)})

    def timestamp(value):
        instant = datetime.fromisoformat(value)
        require(instant.tzinfo is not None, "Missing timestamp offset.")
        minute = instant.timestamp() / 60
        require(origin <= minute <= limit and (minute - origin) % tick == 0,
                "Timestamp lies off-grid or outside the horizon.")
        return int(minute)
    for row in result["activities"]:
        key = row["id"]
        require(key in tasks and key not in spans, f"Unexpected or duplicate scheduled activity: {key}.")
        a, b = (timestamp(row[name]) for name in ("start", "finish"))
        segments = [(timestamp(left), timestamp(right)) for left, right in row["segments"]]
        require(segments and (a, b) == (segments[0][0], segments[-1][1]), f"Invalid span for {key}.")
        task = tasks[key]
        if "not_before" in task:
            require(a >= parse_minute(task["not_before"], zone, tick), f"Early start for {key}.")
        for left, right in segments:
            require(left <= right and all(any(lo <= left and right <= hi for lo, hi in windows)
                                         for windows in calendars[key]), f"Calendar violation for {key}.")
        retain = False
        if key in splits:
            (count, minimum, overhead, retain, voluntary), windows = splits[key]
            require(len(segments) <= count and sum(y - x for x, y in segments) ==
                    (durations[key] + overhead * (len(segments) - 1)) * tick, f"Invalid split duration for {key}.")
            slots = []
            for index, (left, right) in enumerate(segments):
                require(right - left >= max(minimum, 1 + (overhead if index else 0)) * tick,
                        f"Short segment for {key}.")
                slot = next(i for i, (lo, hi) in enumerate(windows)
                            if origin + lo * tick <= left and right <= origin + hi * tick)
                slots.append(slot)
                if index:
                    prior_end = segments[index - 1][1]
                    require(prior_end < left, f"Overlapping or contiguous split segments for {key}.")
                    if not voluntary:
                        prior_slot = slots[index - 1]
                        require(slot == prior_slot + 1 and prior_end == origin + windows[prior_slot][1] * tick
                                and left == origin + windows[slot][0] * tick, f"Voluntary pause for {key}.")
        elif key not in strength:
            require(segments == [(a, b)] and b - a == durations[key] * tick, f"Invalid duration for {key}.")
        else:
            require(segments == [(a, b)], f"Split release hold for {key}.")
        for rid, units in task["resources"].items():
            for left, right in ([(a, b)] if retain and rid not in supplies else segments):
                occupy(rid, units, left, right, key,
                       "retained_gap" if retain and rid not in supplies else "working_time")
        spans[key], segment_map[key] = (a, b), segments
    require(spans.keys() == tasks.keys(), "Incomplete schedule.")
    require(result.get("blocked_activities", {}) == blocked and
            set(result.get("conditional_activities", [])) == conditional & spans.keys(),
            "Release classification mismatch.")
    for key, recorded_at in recorded.items():
        if key in spans:
            require(spans[key][1] <= recorded_at, f"Inspection finishes after recorded pass for {key}.")
    for key, (pour, minimum, fixed) in strength.items():
        if key in spans:
            anchor = spans[pour][1]
            expected = max(anchor + round_duration(minimum, tick), fixed if fixed is not None else anchor)
            require(spans[key] == (anchor, expected), f"Invalid strength-release timing for {key}.")
    expected_reservations = []
    for key, rid, units, start, releases, lead, covered in reservations:
        first = spans[start][0]
        last = max((stamp if stamp is not None else spans[activity][finish]) + delay * tick
                   for activity, finish, stamp, delay in releases) + lead * tick
        require(first <= last and all(first <= a <= b <= last for c in covered for a, b in segment_map[c]),
                f"Reservation coverage violation for {key}.")
        occupy(rid, units, first, last, key, "continuous_elapsed")
        expected_reservations.append({"reservation_id": key, "resource_id": rid, "quantity": units,
                                      "start": display(first, zone), "finish": display(last, zone)})
    require(result.get("reservations", []) == expected_reservations, "Reservation output mismatch.")
    for rid, (scale, cap) in supplies.items():
        for left, right in local_days(origin, limit, zone, tick):
            draw = sum(max(0, min(right, b) - max(left, a)) * tasks[key]["resources"].get(rid, 0)
                       for key, segments in segment_map.items() for a, b in segments)
            require(cap is None or draw <= cap * scale * 60, f"Daily concrete supply limit exceeded for {rid}.")
            if draw or cap is not None:
                supply_checks.append({"resource_id": rid, "date": display(left, zone)[:10],
                                      "draw_m3_exact": str(Fraction(draw, scale * 60)),
                                      "cap_m3_exact": str(cap) if cap is not None else None,
                                      "daily_limit_status": "PASS" if cap is not None else "NOT_DECLARED"})
    capacity_checks = []
    for rid, events in usage.items():
        periods = profiles[rid]
        start_capacity = {left: value for left, _, value in periods}
        load = peak = 0
        capacity = periods[0][2]
        for minute in sorted(events.keys() | start_capacity.keys()):
            capacity = start_capacity.get(minute, capacity)
            load += events[minute]
            peak = max(peak, load)
            require(load <= capacity, f"Overcapacity for {rid} at {display(minute, zone)}.")
        scale = supplies[rid][0] if rid in supplies else 1
        capacity_checks.append({"resource_id": rid, "peak": peak if scale == 1 else peak / scale,
                                "status": "PASS", "capacity_periods": [
                                    {"start": display(left, zone), "finish": display(right, zone),
                                     "capacity": value if scale == 1 else value / scale}
                                    for left, right, value in periods]})
    for left, right, lag in links:
        require(spans[left][1] + lag * tick <= spans[right][0], f"Precedence violation: {left} → {right}.")
    finish = max(end for _, end in spans.values())
    for key, deadline in deadlines:
        require((finish if key == "project" else spans[key][1]) <= deadline, f"Missed deadline for {key}.")
    require(result["objective_minutes"] == finish - origin
            and result["completion_local"] == display(finish, zone), "Makespan mismatch.")
    return {"resource_occupancy": ledger, "resource_conflicts": [],
            "capacity_checks": capacity_checks, "supply_checks": supply_checks,
            "covered_activity_checks": sum(len(row[-1]) for row in reservations)}


def coverage_contradiction(reservations, links, durations):
    from .advanced import closure

    graph = [(left, right) for left, right, _ in links]
    for key, _, _, start, releases, lead, covered in reservations:
        for activity in covered:
            if activity != start and durations[activity] > 0 and start in closure([activity], graph):
                return {"code": "STRUCTURAL_INFEASIBILITY", "cause": "RESERVATION_COVERAGE_PREDECESSOR",
                        "reservation_id": key, "covered_activity_id": activity, "start_activity_id": start}
            # C01 prohibits coverage of precedence successors of activity release events.
            if any(stamp is None and not delay and activity != endpoint
                   and activity in closure([endpoint], graph) for endpoint, _, stamp, delay in releases):
                return {"code": "STRUCTURAL_INFEASIBILITY", "cause": "RESERVATION_COVERAGE_SUCCESSOR",
                        "reservation_id": key, "covered_activity_id": activity,
                        "release_activity_ids": sorted({event[0] for event in releases})}
    return None


def _without_deadline_diagnostic(problem, zone, origin, limit, budget):
    diagnostic = {"code": "INFEASIBLE", "cause": "UNDETERMINED",
                  "message": "No schedule fits the declared model and horizon."}
    if budget <= 0 or problem.get("deadlines") or any("latest_finish" in row for row in problem["activities"]):
        return diagnostic, 0.0
    try:
        extended = datetime.fromtimestamp(limit * 60, zone) + timedelta(days=14)
        candidate = {**problem, "horizon_end": extended.isoformat(timespec="minutes")}
        probe = solve(candidate, time_limit=min(budget, 1.0), _probe_horizon=False)
    except (OverflowError, OSError, ValueError):
        return diagnostic, 0.0
    diagnostic["extended_horizon_status"] = probe["status"]
    if probe["validated"] and origin + probe["objective_minutes"] > limit:
        diagnostic.update(code="HORIZON_EXHAUSTED", cause="VERIFIED_EXTENDED_HORIZON_SCHEDULE",
                          message="A validated schedule exists beyond the declared horizon.",
                          witness_completion=probe["completion_local"])
    return diagnostic, probe["runtime_seconds"]


def solve(problem, *, time_limit=10.0, _probe_horizon=True):
    """Return a verified controlled schedule or a structured diagnostic."""
    from .controlled_metadata import check_metadata

    result = {"timestamp_source": None, "secondary_solver_status": None,
              "primary_runtime_seconds": 0.0, "secondary_runtime_seconds": 0.0,
              "diagnostic_runtime_seconds": 0.0, "optimality_gap_minutes": None,
              "ignored_calendar_exceptions": [], "solver_status": None, "solver_scope": "controlled", "objective_minutes": None, "lower_bound_minutes": None,
              "optimality_gap": None, "runtime_seconds": 0.0, "real_project_eligible": False,
              "activities": [], "validated": False}
    try:
        require(isfinite(time_limit) and time_limit > 0, "Time limit must be positive.")
        # Check the scope before any metadata can be echoed back.
        require(problem["scope"] == "hypothetical_fixture_only", "Controlled inputs only.")
        registered = check_metadata(problem, require)
        prepared = prepare(problem, ignored_exceptions=result["ignored_calendar_exceptions"])
        result["pending_approvals"] = registered
    except SchedulingError as error:
        return dict(result, status="INFEASIBLE" if error.code in INFEASIBLE else "MODEL_INVALID",
                    diagnostic={"code": error.code, "message": str(error), **error.details})
    except (KeyError, TypeError, ValueError, AttributeError, ZoneInfoNotFoundError, OverflowError) as error:
        return dict(result, status="MODEL_INVALID",
                    diagnostic={"code": "MISSING_INPUT" if isinstance(error, KeyError) else "MODEL_INVALID",
                                "message": str(error)})
    (zone, origin, limit, tick, tasks, capacities, domains, durations, _,
     links, deadlines, lower, advanced) = prepared
    recorded, strength, conditional, blocked, reservations, supplies, splits, profiles = advanced
    contradiction = coverage_contradiction(reservations, links, durations)
    if contradiction:
        return dict(result, status="INFEASIBLE", diagnostic=contradiction)
    from .advanced import add_daily_limits, add_split
    model = cp_model.CpModel()
    horizon = (limit - origin) // tick
    starts, ends = {}, {}
    intervals, demands = defaultdict(list), defaultdict(list)
    pieces = {}
    for key, task in tasks.items():
        starts[key] = model.new_int_var_from_domain(cp_model.Domain.from_intervals(domains[key]), f"start:{key}")
        ends[key] = model.new_int_var(0, horizon, f"finish:{key}")
        retain = False
        if key in splits:
            policy, windows = splits[key]
            segments = add_split(model, key, starts[key], ends[key], durations[key], horizon, windows, policy)
            retain = policy[3]
        elif key in strength:
            segments = [(starts[key], ends[key], None, None)]
        else:
            interval = model.new_interval_var(starts[key], durations[key], ends[key], key)
            segments = [(starts[key], ends[key], None, interval)]
        pieces[key] = segments
        span = None
        if retain:
            length = model.new_int_var(0, horizon, f"retained-length:{key}")
            span = model.new_interval_var(starts[key], length, ends[key], f"retained:{key}")
        for rid, units in task["resources"].items():
            uses = [span] if span is not None and rid not in supplies else [segment[3] for segment in segments]
            intervals[rid].extend(uses)
            demands[rid].extend([units] * len(uses))
    for key, at in recorded.items():
        if key in ends:
            model.add(ends[key] <= (at - origin) // tick)
    for key, (pour, minimum, fixed) in strength.items():
        if key in ends:
            model.add(starts[key] == ends[pour])
            expressions = [ends[pour] + round_duration(minimum, tick) // tick]
            if fixed is not None:
                expressions.append((fixed - origin) // tick)
            model.add_max_equality(ends[key], expressions)
    reservation_ends = {}
    for key, rid, units, start, releases, lead, covered in reservations:
        expressions = [((stamp - origin) // tick if stamp is not None
                        else (ends if finish else starts)[activity]) + delay
                       for activity, finish, stamp, delay in releases]
        tail = max(delay for _, _, _, delay in releases)
        release = model.new_int_var(0, horizon + tail, f"release:{key}")
        model.add_max_equality(release, expressions)
        length = model.new_int_var(0, horizon + tail + lead, f"reservation-length:{key}")
        end = release + lead
        intervals[rid].append(model.new_interval_var(starts[start], length, end, key))
        demands[rid].append(units)
        reservation_ends[key] = end
        for activity in covered:
            model.add(starts[activity] >= starts[start])
            model.add(ends[activity] <= end)
    add_daily_limits(model, supplies, tasks, pieces, horizon, origin, limit, zone, tick)
    for rid in intervals:
        capacity = capacities[rid]
        for left, right, value in profiles[rid]:
            if value < capacity:
                intervals[rid].append(model.new_fixed_size_interval_var(
                    (left - origin) // tick, (right - left) // tick, f"{rid}:capacity:{left}"))
                demands[rid].append(capacity - value)
        model.add_cumulative(intervals[rid], demands[rid], capacity)
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
    solver.parameters.num_search_workers = 8 if len(tasks) >= 40 and not labels else 1
    status = solver.solve(model)
    runtime = solver.wall_time
    result.update(status=solver.status_name(status), solver_status=solver.status_name(status),
                  runtime_seconds=runtime, primary_runtime_seconds=runtime)
    if status == cp_model.INFEASIBLE:
        core = [labels[index] for index in solver.sufficient_assumptions_for_infeasibility()]
        if core:
            # A core need not be minimal and can contain deadlines even if the base is infeasible.
            model.clear_assumptions()
            check = cp_model.CpSolver()
            check.parameters.max_time_in_seconds = max(0.001, time_limit - runtime)
            base = check.solve(model)
            result["runtime_seconds"] += check.wall_time
            result["diagnostic_runtime_seconds"] += check.wall_time
            if base in (cp_model.FEASIBLE, cp_model.OPTIMAL):
                result["diagnostic"] = {"code": "INFEASIBLE_DEADLINE", "deadlines": core}
            else:
                result["diagnostic"] = {"code": "INFEASIBLE", "deadline_candidates": core,
                                        "without_deadlines_status": check.status_name(base)}
        else:
            budget = time_limit - runtime if _probe_horizon else 0
            diagnostic, spent = _without_deadline_diagnostic(
                problem, zone, origin, limit, budget)
            result["diagnostic"] = diagnostic
            result["runtime_seconds"] += spent
            result["diagnostic_runtime_seconds"] += spent
        return result
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if status == cp_model.UNKNOWN:
            result["lower_bound_minutes"] = max(lower, ceil(solver.best_objective_bound)) * tick
        return result
    objective = solver.value(makespan)
    bound = objective if status == cp_model.OPTIMAL else max(lower, ceil(solver.best_objective_bound))
    result["timestamp_source"] = "primary"
    # Choose early dates within the proven makespan, using only the remaining solve budget.
    if status == cp_model.OPTIMAL and time_limit > runtime and len(tasks) < 40 and _probe_horizon:
        model.add(makespan == objective)
        model.minimize(sum(starts.values()))
        tie_break = cp_model.CpSolver()
        tie_break.parameters.num_search_workers = 1
        tie_break.parameters.max_time_in_seconds = time_limit - runtime
        tie_status = tie_break.solve(model)
        result["runtime_seconds"] += tie_break.wall_time
        result["secondary_runtime_seconds"] = tie_break.wall_time
        result["secondary_solver_status"] = tie_break.status_name(tie_status)
        if tie_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            solver = tie_break
            result["timestamp_source"] = "secondary"
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
    result.update(objective_minutes=objective * tick, lower_bound_minutes=bound * tick,
                  optimality_gap_minutes=(objective - bound) * tick,
                  optimality_gap=(objective - bound) / max(1, abs(objective)),
                  completion_local=display(origin + objective * tick, zone))
    for key in ("cost", "fixture_exceptions", "cpm_baseline_minutes", "resources"):
        if key in problem:
            result[key] = problem[key]
    for key in ("inspection_pass_events", "strength_events", "release_events", "calendar_exceptions",
                "project_calendar"):
        if key in problem:
            result[key] = problem[key]
    result["reservation_declarations"] = problem.get("reservations", [])
    result.update(validate(problem, result))
    result["validated"] = True
    return result

