"""Date capacity declarations and half-open calendar-day profiles."""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

from pmi_core.scheduling.calendar import parse_minute

from .schemas import integer, require


UNITS = {
    "labour_trade": {"worker"}, "equipment": {"machine"}, "inspector": {"inspector"},
    "reusable_asset": {"set", "piece"}, "supply_source": {"m3/h"},
    "renewable": {"worker", "machine", "inspector"},
}


def capacity_periods(resource, base, scale, zone, origin, limit, tick):
    """Return an outside-calendar-neutral capacity profile in absolute UTC minutes."""
    changes = resource.get("capacity_by_date")
    if changes is None:
        return [(origin, limit, base)]
    require(isinstance(changes, dict), "Date capacities must be an object or null.", "INVALID_CAPACITY_OVERRIDE")
    require(not changes or resource.get("unit") in UNITS[resource["kind"]],
            "Date capacity overrides require compatible resource units.", "INVALID_CAPACITY_OVERRIDE")
    if isinstance(resource["calendar"], dict):
        zone = ZoneInfo(resource["calendar"]["timezone"])
    overrides = []
    for label, value in sorted(changes.items()):
        try:
            day = date.fromisoformat(label)
        except (TypeError, ValueError):
            require(False, f"Invalid date capacity key: {label!r}.", "INVALID_CAPACITY_OVERRIDE")
        require(day.isoformat() == label and integer(value) and integer(value * scale),
                "Date capacities require ISO dates and nonnegative integers in the resource unit.",
                "INVALID_CAPACITY_OVERRIDE")
        require(not resource.get("explicit_none") or value == 0,
                "An explicit-none resource cannot acquire capacity via an override.", "INVALID_CAPACITY_OVERRIDE")
        start = parse_minute(f"{day.isoformat()}T00:00", zone)
        end = parse_minute(f"{(day + timedelta(days=1)).isoformat()}T00:00", zone)
        require((start - origin) % tick == 0 and (end - origin) % tick == 0,
                "Local capacity boundaries do not align to the scheduling tick.", "TICK_MISALIGNED")
        if start < limit and end > origin:
            overrides.append((max(start, origin), min(end, limit), value * scale))
    periods = []
    cursor = origin
    for start, end, value in overrides:
        if cursor < start:
            periods.append((cursor, start, base))
        periods.append((start, end, value))
        cursor = end
    if cursor < limit:
        periods.append((cursor, limit, base))
    return periods

