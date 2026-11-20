"""Separate physical plans from conservative scheduling demand."""

from fractions import Fraction

from pmi_core.scheduling.calendar import display
from .advanced import local_days
from .schemas import require


def physical_volume(value):
    require(type(value) in (int, float, str), "Invalid planned concrete volume.")
    amount = Fraction(str(value))
    require(amount > 0, "Planned concrete volume must be positive.")
    return amount


def report_supply(problem, tasks, segments, supplies, splits, origin, limit, zone, tick):
    days = list(local_days(origin, limit, zone, tick)) if supplies else []
    activities, sources, daily = [], [], []
    for rid, (scale, cap) in supplies.items():
        by_day = {left: [Fraction(0), Fraction(0), Fraction(0), False, False] for left, _ in days}
        source_physical = Fraction(0)
        source_work = source_restart = Fraction(0)
        has_unknown = False
        for key, task in tasks.items():
            if rid not in task["resources"]:
                continue
            rate = Fraction(task["resources"][rid], scale * 60)
            spans = segments[key]
            overhead = splits[key][0][2] * tick if key in splits else 0
            placed = physical_volume(task["planned_placed_volume_m3"]) if "planned_placed_volume_m3" in task else None
            active_days = {}
            working = restart = Fraction(0)
            for index, (a, b) in enumerate(spans):
                production_start = a + (overhead if index else 0)
                working += (b - production_start) * rate
                restart += (production_start - a) * rate
                for left, right in days:
                    production = max(0, min(right, b) - max(left, production_start))
                    restarting = max(0, min(right, production_start) - max(left, a))
                    if production:
                        active_days[left] = active_days.get(left, Fraction(0)) + production * rate
                    if production or restarting:
                        day = by_day[left]
                        day[0] += production * rate
                        day[1] += restarting * rate
                        day[4] = True
            for left in active_days:
                if task.get("placement_profile") == "declared_constant_rate":
                    by_day[left][2] += active_days[left]
                elif placed is None or len(active_days) != 1:
                    by_day[left][3] = True
                else:
                    by_day[left][2] += placed
            has_unknown |= placed is None
            source_physical += placed or 0
            source_work += working
            source_restart += restart
            activities.append({"activity_id": key, "resource_id": rid,
                               **quantities(placed, working, restart)})
        for left, values in by_day.items():
            working, restart, placed, unknown, has_work = values
            require(cap is None or working + restart <= cap, f"Daily concrete supply limit exceeded for {rid}.")
            if has_work or cap is not None:
                daily.append({"resource_id": rid, "date": display(left, zone)[:10],
                              "cap_m3_exact": str(cap) if cap is not None else None,
                              "daily_limit_status": "PASS" if cap is not None else "NOT_DECLARED",
                              **quantities(None if unknown else placed, working, restart)})
        sources.append({"resource_id": rid,
                        **quantities(None if has_unknown else source_physical, source_work, source_restart)})
    return {"supply_by_activity": activities, "supply_by_source": sources, "supply_checks": daily,
            "supply_totals": {f"aggregate_{k}": v for k, v in rollup(sources).items()} if sources else None}


def quantities(placed, working, restart):
    return {"planned_placed_volume_m3": None if placed is None else str(placed),
            "productive_capacity_allowance_m3": str(working),
            "restart_capacity_allowance_m3": str(restart),
            "total_capacity_allowance_m3": str(working + restart)}


def rollup(sources):
    result = {}
    for key in quantities(None, Fraction(0), Fraction(0)):
        values = [row[key] for row in sources]
        result[key] = None if any(value is None for value in values) else str(sum(map(Fraction, values)))
    return result
