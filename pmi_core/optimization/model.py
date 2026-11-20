"""CP-SAT interval and cumulative model construction."""
from collections import defaultdict
from ortools.sat.python import cp_model
from pmi_core.scheduling.calendar import display, round_duration
from .diagnostics import deadline_scope

def build_model(prepared):
    (zone, origin, limit, tick, tasks, capacities, domains, durations, _, links, deadlines, lower, advanced) = prepared
    recorded, strength, conditional, blocked, reservations, supplies, splits, profiles = advanced
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
    return model, starts, ends, pieces, reservation_ends, makespan, labels
