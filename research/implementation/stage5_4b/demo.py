"""Adapt the unchanged Task 6 construction fixture and holiday sensitivity."""

from collections import defaultdict
from copy import deepcopy
from decimal import Decimal
from graphlib import TopologicalSorter
from hashlib import sha256

from pmi_core.scheduling.calendar import display, round_duration

from .engine import prepare

from .fixtures import REFERENCES, approvals, read_json, remap


CORRECTION = REFERENCES / "corrections/C01_column_reservation_coverage"


def benchmark_path(holiday, version):
    label = "holiday" if holiday else "original"
    manifest = read_json(CORRECTION / "correction_manifest.json")
    if version not in {"v1.0", "v1.1"}:
        raise ValueError(f"Unknown benchmark version: {version}.")
    record = manifest["corrected" if version == "v1.1" else "historical_preserved"][label]
    if version == "v1.1" and record["path"] != manifest["benchmark_inputs_for_acceptance"][label]:
        raise ValueError("Inconsistent corrected benchmark source in the manifest.")
    path = REFERENCES / record["path"]
    if sha256(path.read_bytes()).hexdigest() != record["sha256"]:
        raise ValueError(f"Benchmark input hash mismatch: {path}.")
    return path


def construction_demo(holiday=False, *, version="v1.0", coverage_sensitivity=False):
    if coverage_sensitivity and version != "v1.0":
        raise ValueError("Coverage sensitivity applies only to historical v1.0.")
    source = read_json(benchmark_path(holiday, version))
    project = source["project"]
    calendars = {
        row["calendar_id"]: {k: v for k, v in row.items() if k not in {"calendar_id", "note"}}
        for row in source["calendars"]
    }
    resources = {}
    for row in source["resources"]:
        rid = row["resource_id"]
        resources[rid] = {
            **{k: row[k] for k in ("resource_id", "display_name", "unit", "capacity", "input_state", "explicit_none", "evidence_ref")},
            "kind": row["resource_class"],
            "calendar": ("continuous" if row["availability"] == "continuous"
                         else calendars[row["calendar_ref"]]),
        }
    supply = source["supply"]
    rid = supply["resource_id"]
    if (supply["rate_capacity_m3_h"] != resources[rid]["capacity"]
            or not supply["concurrent_with_placement"]
            or resources[rid]["calendar"] != calendars[supply["calendar_ref"]]):
        raise ValueError("Conflicting construction demo supply declarations.")
    if "max_volume_per_day_m3" in supply:
        resources[rid]["max_volume_per_day_m3"] = supply["max_volume_per_day_m3"]
    modes = {row["mode_id"]: row for row in source["crew_modes"]}
    tasks, inspections, strength = [], [], []
    for row in source["activities"]:
        key = row["id"]
        task = {
            "id": key, "kind": row["kind"], "duration_minutes": row["duration_minutes"],
            "resources": row["demands"], "interruption": row["interruption"] or "non_interruptible",
            "reference_cost_eur": row["cost_eur"], "input_state": row["input_state"],
            "pending_approval_ids": row["approval_ids"],
        }
        if row["mode"]:
            mode = modes[row["mode"]]
            working = {k: v for k, v in task["resources"].items() if k != rid}
            if mode["execution_mode"] != "simultaneous_fixed_crew" or working != mode["units"]:
                raise ValueError(f"Construction demo mode mismatch for {key}.")
            hours = remap(row["worker_hours_by_trade"] | row["machine_hours_by_class"])
            excess = {k: v for k, v in working.items() if k not in hours}
            if excess and (row["work_item"] != "COL-CONC" or excess != {"OFICIAL_1": 1}):
                raise ValueError(f"Undeclared zero-demand occupation for {key}.")
            task.update(crew_mode=row["mode"], crew_mode_input_state=mode["input_state"], positive_capacity={k: working[k] for k in hours},
                        demand_hours=hours)
            if excess:
                task.update(reserved_without_bcca_demand=excess,
                            reservation_reason="R2 retains the full column pour crew.",
                            reservation_approval_ref="AP-X-CREW-01")
        if "pass_event" in row:
            event = row["pass_event"]
            inspections.append({
                "event_id": event["id"], "status": event["status"], "inspection_activity": key,
                "input_state": event.get("input_state", row["input_state"]),
                "gates": [edge["successor"] for edge in source["dependencies"]
                          if edge["predecessor"] == key and edge["condition"] == "inspection pass"],
                **({"at": event["at"]} if "at" in event else {}),
            })
        if "release_event" in row:
            event = row["release_event"]
            anchor, basis = event["anchor"].rsplit(" ", 1)
            if basis != "finish":
                raise ValueError(f"Unsupported demo strength anchor for {key}.")
            strength.append({"event_id": event["id"], "status": event["status"],
                             "pour_activity": anchor, "release_activity": key,
                             "input_state": event.get("input_state", row["input_state"])})
        tasks.append(task)
    reservations = deepcopy(source["reservations"])
    fixture_notes = []
    if coverage_sensitivity:
        # The frozen fixture requires cage-first columns. Task 6's checker uses only
        # FORM-to-STRIP capacity and omits coverage of the earlier cage work.
        for row in reservations:
            start = row["start_event"]["activity_id"]
            if row["resource_id"] != "COL_FORM_SET":
                continue
            before = {edge["predecessor"] for edge in source["dependencies"]
                      if edge["successor"] == start and edge["condition"] == "cage_first"}
            row["covers_activities"] = [key for key in row["covers_activities"] if key not in before]
        fixture_notes.append({
            "scope": "diagnostic_only",
            "change": "Exclude predecessor cage work from column formwork reservation coverage.",
        })
    cost = sum((Decimal(str(task["reference_cost_eur"])) for task in tasks), Decimal(0))
    return {
        "scope": "hypothetical_fixture_only", "timezone": project["timezone"],
        "tick_minutes": source["_meta"]["tick_minutes"], "project_start": project["start_local"],
        "horizon_end": project["horizon_local"], "project_calendar": calendars["PROJECT"],
        "activities": tasks, "resources": resources, "cost": {"total_direct_reference_eur": float(cost)},
        "dependencies": [{k: v for k, v in edge.items() if k not in {"source", "condition"}}
                         for edge in source["dependencies"]],
        "reservations": reservations, "strength_events": strength, "inspection_pass_events": inspections,
        "pending_approvals": approvals(), "fixture_exceptions": fixture_notes,
    }


def cpm_comparison(problem):
    """Calendar/precedence-only baseline and its nominal occupancy conflicts."""
    zone, origin, _, tick, tasks, capacities, domains, durations, _, links, _, _, advanced = prepare(problem)
    recorded, strength, _, _, reservations, _, splits, _ = advanced
    if recorded or splits or any(fixed is not None for _, _, fixed in strength.values()):
        raise ValueError("The demonstration CPM comparison requires fixed intervals and at-minimum releases.")
    incoming = defaultdict(list)
    for left, right, lag in links:
        incoming[right].append((left, lag))
    order = TopologicalSorter({key: {left for left, _ in incoming[key]} for key in tasks}).static_order()
    spans = {}
    for key in order:
        ready = max((spans[left][1] + lag for left, lag in incoming[key]), default=0)
        start = next(max(ready, lo) for lo, hi in domains[key] if hi >= ready)
        length = durations[key]
        if key in strength:
            pour, minimum, _ = strength[key]
            if start != spans[pour][1]:
                raise ValueError("Conflicting at-minimum release anchor in the demonstration.")
            length = round_duration(minimum, tick) // tick
        spans[key] = start, start + length
    holders = defaultdict(list)
    for key, task in tasks.items():
        for rid, units in task["resources"].items():
            holders[rid].append((*spans[key], units, key))
    for key, rid, units, start, releases, lead, _ in reservations:
        end = max((spans[activity][finish] if stamp is None else (stamp - origin) // tick) + delay
                  for activity, finish, stamp, delay in releases)
        holders[rid].append((spans[start][0], end + lead, units, key))
    conflicts = []
    for rid, occupancy in holders.items():
        boundaries = sorted({point for a, b, _, _ in occupancy for point in (a, b)})
        for left, right in zip(boundaries, boundaries[1:]):
            active = [(units, key) for a, b, units, key in occupancy if a <= left < b]
            if sum(units for units, _ in active) <= capacities[rid]:
                continue
            ids = sorted(key for _, key in active)
            if conflicts and conflicts[-1][:1] == [rid] and conflicts[-1][2:] == [left, ids]:
                conflicts[-1][2] = right
            else:
                conflicts.append([rid, left, right, ids])
    elapsed = max(end for _, end in spans.values()) * tick
    return {"makespan_minutes": elapsed, "completion_local": display(origin + elapsed, zone),
            "conflict_intervals": len(conflicts), "over_capacity_pools": sorted({row[0] for row in conflicts})}
