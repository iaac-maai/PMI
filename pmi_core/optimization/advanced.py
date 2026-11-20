"""Construction constraints shared by model construction and timestamp validation."""

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, time, timedelta
from fractions import Fraction
from math import lcm

from .schemas import integer, require, supported
from pmi_core.scheduling.calendar import parse_minute, round_duration


def split_policy(task, tick):
    policy = task.get("split")
    if task.get("interruption", "non_interruptible") == "non_interruptible":
        require(not policy, "Unexpected split policy.", "UNSUPPORTED_CONSTRAINT")
        return None
    require(task["interruption"] == "split_allowed" and isinstance(policy, dict),
            "Missing split policy.", "SPLIT_NOT_AUTHORIZED")
    supported(policy, {"authorization_ref", "max_segments", "min_segment_minutes",
                       "retention_during_gap", "restart_overhead_minutes", "same_mode_on_restart",
                       "voluntary_pause", "cold_joint_authorization_ref", "input_state", "evidence_ref"})
    require(all(key in policy for key in ("authorization_ref", "max_segments", "min_segment_minutes",
                                         "retention_during_gap", "restart_overhead_minutes",
                                         "same_mode_on_restart", "voluntary_pause"))
            and isinstance(policy["authorization_ref"], str) and policy["authorization_ref"].strip(),
            "Incomplete split authorization or rules.", "SPLIT_NOT_AUTHORIZED")
    require(task["kind"] == "productive" and policy["same_mode_on_restart"] is True
            and policy["retention_during_gap"] in {"release", "retain"}
            and type(policy["voluntary_pause"]) is bool, "Unsupported split combination.",
            "UNSUPPORTED_CONSTRAINT")
    require(not task.get("is_pour") or (isinstance(policy.get("cold_joint_authorization_ref"), str)
            and policy["cold_joint_authorization_ref"].strip()), "Missing cold-joint authorization.",
            "SPLIT_NOT_AUTHORIZED")
    require(integer(policy["max_segments"], 2) and policy["min_segment_minutes"] > 0,
            "Invalid split count or minimum length.")
    return (policy["max_segments"], round_duration(policy["min_segment_minutes"], tick) // tick,
            round_duration(policy["restart_overhead_minutes"], tick) // tick,
            policy["retention_during_gap"] == "retain", policy["voluntary_pause"])


def closure(seeds, edges):
    reached = set(seeds)
    outgoing = defaultdict(set)
    for left, right in edges:
        outgoing[left].add(right)
    pending = list(reached)
    while pending:
        for key in outgoing[pending.pop()] - reached:
            reached.add(key)
            pending.append(key)
    return reached


def event_constraints(problem, zone, tick):
    tasks = {task["id"]: task for task in problem["activities"]}
    links = problem["dependencies"]
    recorded, strength, named, conditional, blocked = {}, {}, {}, set(), {}
    for row in problem.get("release_events", []):
        supported(row, {"event_id", "activity_id", "status", "at", "input_state", "evidence_ref"})
        event, activity = row["event_id"], row["activity_id"]
        require(event and event not in named and activity in tasks
                and row["status"] in {"recorded_pass", "hypothetical_recorded_pass"},
                "Invalid explicit recorded release event.")
        stamp = parse_minute(row["at"], zone, tick)
        named[event] = (activity, True, stamp, row["status"])
        latest = parse_minute(row["at"], zone, tick, upper=True)
        recorded[activity] = min(recorded.get(activity, latest), latest)
    for row in problem.get("inspection_pass_events", []):
        supported(row, {"event_id", "inspection_activity", "status", "gates", "at", "input_state", "evidence_ref"})
        key, event, status = row["inspection_activity"], row["event_id"], row["status"]
        require(event and event not in named and key in tasks and tasks[key]["kind"] == "inspection",
                "Invalid inspection event identity.")
        require(row["gates"] and all(g in tasks and g != key for g in row["gates"]),
                "Invalid inspection event gates.")
        require(status in {"hypothetical_pass", "recorded_pass", "missing", "failed"},
                "Invalid inspection status.")
        stamp = parse_minute(row["at"], zone, tick, upper=True) if status == "recorded_pass" else None
        named[event] = (key, True, parse_minute(row["at"], zone, tick) if stamp is not None else None, status)
        if status == "recorded_pass":
            recorded[key] = min(recorded.get(key, stamp), stamp)
        for gate in row["gates"]:
            links.append({"predecessor": key, "successor": gate, "relation": "FS",
                          "lag_basis": "elapsed", "lag_minutes": 0})
            if stamp is not None:
                set_not_before(tasks[gate], row["at"], zone)
            if status == "missing":
                conditional.add(gate)
            if status == "failed":
                blocked[gate] = "INSPECTION_FAILED"
    for row in problem.get("strength_events", []):
        supported(row, {"event_id", "release_activity", "pour_activity", "kind", "status", "at",
                        "test_age_hours_after_pour", "acceptance_criterion_ref", "input_state", "evidence_ref"})
        key, event, status = row["release_activity"], row["event_id"], row["status"]
        require(event and event not in named and key in tasks and key not in strength
                and tasks[key]["kind"] == "elapsed_hold", "Invalid strength release identity.")
        incoming = [edge for edge in links if edge["successor"] == key]
        pour = row.get("pour_activity")
        if pour is None and len(incoming) == 1:
            pour = incoming[0]["predecessor"]
        require(pour in tasks and tasks[pour]["kind"] == "productive", "Missing strength-release pour anchor.",
                "MISSING_INPUT")
        require(status in {"recorded_pass", "hypothetical_recorded_pass", "hypothetical_pass_at_minimum",
                           "planned", "pending_result", "missing", "failed"}, "Invalid strength status.")
        stamp = None
        minimum = tasks[key]["duration_minutes"]
        if status in {"recorded_pass", "hypothetical_recorded_pass"}:
            stamp = parse_minute(row["at"], zone, tick)
        if status in {"planned", "pending_result"}:
            require(row.get("acceptance_criterion_ref"), "Missing strength test criterion.", "MISSING_INPUT")
            minimum = max(minimum, round_duration(row["test_age_hours_after_pour"] * 60, tick))
        if status in {"planned", "pending_result", "missing"}:
            conditional.add(key)
        if status == "failed":
            blocked[key] = "RELEASE_FAILED"
        named[event] = (key, True, None, status)
        strength[key] = (pour, minimum, stamp)
        links.append({"predecessor": pour, "successor": key, "relation": "FS",
                      "lag_basis": "elapsed", "lag_minutes": 0})
    edges = [(edge["predecessor"], edge["successor"]) for edge in links]
    for key, reason in list(blocked.items()):
        blocked.update({descendant: reason for descendant in closure([key], edges)})
    return recorded, strength, named, closure(conditional, edges), blocked


def set_not_before(task, candidate, zone):
    if "not_before" not in task or parse_minute(candidate, zone) > parse_minute(task["not_before"], zone):
        task["not_before"] = candidate


def asset_reservations(problem, named, blocked, tick):
    tasks = {task["id"] for task in problem["activities"]}
    graph = [(edge["predecessor"], edge["successor"]) for edge in problem["dependencies"]]
    output, seen = [], set()

    def endpoint(event):
        kind = event["kind"]
        if kind == "elapsed_after_event":
            supported(event, {"kind", "anchor", "elapsed_minutes"})
            key, finish, stamp, offset = endpoint(event["anchor"])
            return key, finish, stamp, offset + round_duration(event["elapsed_minutes"], tick) // tick
        supported(event, {"kind", "activity_id", "event_id"})
        if kind in {"inspection_pass", "strength_release", "explicit_recorded_event"}:
            event_id = event.get("event_id")
            if event_id is None and kind == "inspection_pass":
                candidates = [eid for eid, record in named.items() if record[0] == event.get("activity_id")]
                event_id = candidates[0] if len(candidates) == 1 else None
            require(event_id in named, "Unknown or ambiguous reservation release event.", "RESERVATION_UNRELEASED")
            key, finish, timestamp, status = named[event_id]
            require(status != "failed", "Failed reservation release.", "RESERVATION_UNRELEASED")
            return key, finish, timestamp, 0
        require(kind in {"activity_start", "activity_finish"}, "Unsupported reservation endpoint.",
                "UNSUPPORTED_CONSTRAINT")
        return event["activity_id"], kind == "activity_finish", None, 0

    for row in problem.get("reservations", []):
        supported(row, {"reservation_id", "resource_id", "quantity", "element_ids", "start_event",
                        "release_condition", "occupancy_basis", "covers_activities", "input_state",
                        "approval_required", "evidence_ref"})
        key, rid, quantity = row["reservation_id"], row["resource_id"], row["quantity"]
        resource = problem["resources"].get(rid, {})
        require(resource, f"Missing reusable resource {rid}.", "MISSING_INPUT")
        require(resource["kind"] == "reusable_asset" and row["occupancy_basis"] == "continuous_elapsed"
                and key and key not in seen, "Invalid reusable reservation.")
        require(row.get("input_state") != "missing" and integer(quantity, 1),
                f"Missing or invalid physical quantity for {key}.", "MISSING_INPUT")
        seen.add(key)
        condition = row["release_condition"]
        supported(condition, {"all_of", "return_lead_minutes", "reshoring", "input_state", "evidence_ref"})
        require(condition.get("input_state") != "missing", "Missing release condition.", "MISSING_INPUT")
        require(condition["reshoring"] == "not_permitted", "Unsupported reshoring configuration.",
                "UNSUPPORTED_CONSTRAINT")
        lead = round_duration(condition["return_lead_minutes"], tick) // tick
        start, finish, stamp, offset = endpoint(row["start_event"])
        require(start in tasks and not finish and stamp is None and not offset,
                "Reservation must begin at a known activity start.", "RESERVATION_UNRELEASED")
        releases = [endpoint(event) for event in condition["all_of"]]
        reachable = closure([start], graph)
        require(releases and all(k in reachable and (k != start or end or delay) for k, end, _, delay in releases),
                f"Unreachable release for {key}.", "RESERVATION_UNRELEASED")
        covered = row["covers_activities"]
        require(covered and set(covered) <= tasks, f"Invalid covered activities for {key}.")
        if start in blocked:
            continue
        require(not (set(covered) | {k for k, _, _, _ in releases}) & blocked.keys(),
                f"Blocked release or covered activity for {key}.", "RESERVATION_UNRELEASED")
        output.append((key, rid, quantity, start, releases, lead, covered))
    return output


def exact_rate(value):
    rate = Fraction(str(value))
    require(rate > 0, "Supply rate must be positive.")
    return rate


def scale_supply(problem):
    supplies = {}
    for rid, resource in problem["resources"].items():
        if resource["kind"] != "supply_source":
            continue
        require(resource.get("unit") == "m3/h", f"Incompatible rate unit for {rid}.")
        require(resource.get("capacity") is not None and resource.get("input_state") != "missing",
                f"Missing supply rate for {rid}.", "MISSING_INPUT")
        capacity = exact_rate(resource["capacity"])
        demands = [(task, exact_rate(task["resources"][rid])) for task in problem["activities"]
                   if rid in task["resources"]]
        scale = lcm(capacity.denominator, *(rate.denominator for _, rate in demands))
        cap = resource.get("max_volume_per_day_m3")
        if cap is not None:
            cap = Fraction(str(cap))
            require(cap >= 0, "Daily concrete supply limit must be nonnegative.")
        supplies[rid] = scale, cap
        resource["capacity"] = int(capacity * scale)
        for task, rate in demands:
            require(task["kind"] == "productive", "Supply demand requires productive work.")
            task["resources"][rid] = int(rate * scale)
    return supplies


def normalize(problem, zone, tick):
    problem = deepcopy(problem)
    recorded, strength, named, conditional, blocked = event_constraints(problem, zone, tick)
    reservations = asset_reservations(problem, named, blocked, tick)
    supplies = scale_supply(problem)
    for task in problem["activities"]:
        if any(rid in supplies for rid in task["resources"]):
            task["is_pour"] = True
    problem["activities"] = [task for task in problem["activities"] if task["id"] not in blocked]
    problem["dependencies"] = [edge for edge in problem["dependencies"]
                               if not {edge["predecessor"], edge["successor"]} & blocked.keys()]
    return problem, recorded, strength, conditional, blocked, reservations, supplies


def add_split(model, key, start, end, duration, horizon, windows, policy):
    count, minimum, overhead, _, voluntary = policy
    count = min(count, duration // max(1, minimum - overhead) + 1, horizon)
    pieces, productive = [], []
    for index in range(count):
        present = model.new_bool_var(f"{key}:present:{index}")
        a = model.new_int_var(0, horizon, f"{key}:segment-start:{index}")
        b = model.new_int_var(0, horizon, f"{key}:segment-end:{index}")
        work = model.new_int_var(0, duration, f"{key}:work:{index}")
        restart = overhead if index else 0
        interval = model.new_optional_interval_var(a, work + restart, b, present, f"{key}:{index}")
        slot = model.new_int_var(0, len(windows) - 1, f"{key}:window:{index}")
        left = model.new_int_var(0, horizon, f"{key}:open:{index}")
        right = model.new_int_var(0, horizon, f"{key}:close:{index}")
        model.add_element(slot, [lo for lo, _ in windows], left)
        model.add_element(slot, [hi for _, hi in windows], right)
        model.add(a >= left).only_enforce_if(present)
        model.add(b <= right).only_enforce_if(present)
        model.add(work >= max(1, minimum - restart)).only_enforce_if(present)
        model.add(work == 0).only_enforce_if(~present)
        if not index:
            model.add(present == 1)
            model.add(start == a)
        else:
            pa, pb, pp, pi = pieces[-1]
            model.add_implication(present, pp)
            model.add(a > pb).only_enforce_if(present)
            if not voluntary:
                model.add(pb == previous_right).only_enforce_if(present)
                model.add(a == left).only_enforce_if(present)
                model.add(slot == previous_slot + 1).only_enforce_if(present)
        model.add(end >= b).only_enforce_if(present)
        model.add(b == 0).only_enforce_if(~present)
        productive.append(work)
        pieces.append((a, b, present, interval))
        previous_right, previous_slot = right, slot
    model.add(sum(productive) == duration)
    model.add_max_equality(end, [piece[1] for piece in pieces])
    return pieces


def local_days(origin, limit, zone, tick):
    day = datetime.fromtimestamp(origin * 60, zone).date()
    last = datetime.fromtimestamp(limit * 60, zone).date()
    while day <= last:
        following = day + timedelta(days=1)
        left = max(origin, parse_minute(datetime.combine(day, time.min).isoformat(), zone))
        right = min(limit, parse_minute(datetime.combine(following, time.min).isoformat(), zone))
        if left < right:
            require((left - origin) % tick == (right - origin) % tick == 0,
                    "Daily supply boundary lies off the grid.", "TICK_MISALIGNED")
            yield left, right
        day = following


def add_daily_limits(model, supplies, tasks, pieces, horizon, origin, limit, zone, tick):
    for rid, (scale, cap) in supplies.items():
        if cap is None:
            continue
        for left, right in local_days(origin, limit, zone, tick):
            lo, hi = (left - origin) // tick, (right - origin) // tick
            volumes = []
            for key, task in tasks.items():
                if rid not in task["resources"]:
                    continue
                for index, (a, b, present, _) in enumerate(pieces[key]):
                    begin = model.new_int_var(0, horizon, f"{key}:{lo}:{index}:delivery-start")
                    finish = model.new_int_var(0, horizon, f"{key}:{lo}:{index}:delivery-end")
                    overlap = model.new_int_var(0, hi - lo, f"{key}:{lo}:{index}:overlap")
                    model.add_max_equality(begin, [a, lo])
                    model.add_min_equality(finish, [b, hi])
                    model.add_max_equality(overlap, [0, finish - begin])
                    volumes.append(overlap * task["resources"][rid])
            model.add(sum(volumes) <= (cap * scale * 60) // tick)

