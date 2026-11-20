"""Timestamp checks on serialized results."""
from collections import defaultdict
from datetime import datetime
from pmi_core.scheduling.calendar import display, parse_minute, round_duration
from .preparation import prepare
from .schemas import require
from .supply_reporting import report_supply

def validate(problem, result, *, registry):
    """Recheck timestamps without CP-SAT variables using the model's shared input preparation.

    Calendar expansion and event normalization are shared. External acceptance uses
    the separate Agent 2 oracle on the source fixtures.
    """
    (zone, origin, limit, tick, tasks, capacities, _, durations, calendars,
     links, deadlines, _, advanced) = prepare(problem, registry=registry)
    recorded, strength, conditional, blocked, reservations, supplies, splits, profiles = advanced
    spans, segment_map, usage = {}, {}, defaultdict(lambda: defaultdict(int))
    ledger = []

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
            if rid in supplies:
                overhead = splits[key][0][2] * tick if key in splits else 0
                for index, (left, right) in enumerate(segments):
                    production_start = left + (overhead if index else 0)
                    if production_start > left:
                        occupy(rid, units, left, production_start, key, "restart_capacity_allowance")
                    occupy(rid, units, production_start, right, key, "productive_capacity_allowance")
            else:
                for left, right in ([(a, b)] if retain else segments):
                    occupy(rid, units, left, right, key, "retained_gap" if retain else "working_time")
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
            "capacity_checks": capacity_checks,
            **report_supply(problem, tasks, segment_map, supplies, splits, origin, limit, zone, tick),
            "covered_activity_checks": sum(len(row[-1]) for row in reservations)}
