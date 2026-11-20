"""Calendar, resource and precedence preparation."""
from datetime import date
from graphlib import TopologicalSorter
from math import isfinite
import re
from zoneinfo import ZoneInfo
from pmi_core.scheduling.calendar import build_windows, display, parse_minute, round_duration
from .schemas import integer, require, supported
from .diagnostics import deadline_scope

DEFERRED = {
    "hypothetical_strength_events", "supply_sources", "pour_supply_demands",
    "split_policies", "events",
}
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


def prepare(problem, *, registry, ignored_exceptions=None):
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
                         "crew_mode_input_state", "evidence_ref", "planned_placed_volume_m3", "placement_profile"})
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
    from .supply_reporting import physical_volume

    for task in problem["activities"]:
        if "planned_placed_volume_m3" in task:
            require(len(task["resources"].keys() & supplies.keys()) == 1,
                    "Physical concrete volume requires exactly one declared supply source.")
            physical_volume(task["planned_placed_volume_m3"])
        if "placement_profile" in task:
            require(task["placement_profile"] == "declared_constant_rate"
                    and "planned_placed_volume_m3" in task,
                    "A placement profile requires a declared physical volume and supported profile.")
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
        reason = registry.calendar_exception_reason(exception_input, entry)
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
        if "placement_profile" in task:
            from fractions import Fraction

            rid, = task["resources"].keys() & supplies.keys()
            capacity_volume = Fraction(task["resources"][rid] * duration, supplies[rid][0] * 60)
            require(capacity_volume == physical_volume(task["planned_placed_volume_m3"]),
                    "Declared constant placement profile does not reconcile to planned physical volume.")
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
