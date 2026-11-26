"""Qualify and estimate the registered, synthetic IFC4 frame."""
from itertools import combinations
from math import isclose
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from uuid import NAMESPACE_URL, uuid5

import ifcopenshell
from ifcopenshell import guid
from ifcopenshell.api import run

from pmi_core.application import _digest, _read
from pmi_core.cli import main as construction_cli
from pmi_core.estimation.engine import estimate_operation, _external_resources
from pmi_core.estimation.references import load_references, number
from pmi_core.schemas.bim import stable_id
from research.implementation.stage5_2.create_frame import create_frame

STATE = "hypothetical_fixture"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REFERENCE = ROOT / "research/validation/engineering_approval_review/stage5_3_reference_selection.csv"


def resource_id(name):
    import unicodedata
    return re.sub(r"[^A-Z0-9]+", "_", unicodedata.normalize("NFKD", name)
                  .encode("ascii", "ignore").decode().upper()).strip("_")


def create_candidate(path):
    """Create an explicitly synthetic frame with new geometry and identities."""
    with TemporaryDirectory() as folder:
        base = Path(folder) / "base.ifc"
        create_frame(base)
        model = ifcopenshell.open(str(base))
    elements = {obj.is_a(): obj for obj in model.by_type("IfcElement")}
    column = elements["IfcColumn"]
    column.Representation.Representations[0].Items[0].Depth = 3400.
    for name, elevation in (("IfcBeam", 3400.), ("IfcSlab", 3900.)):
        element = elements[name]
        location = element.ObjectPlacement.RelativePlacement.Location
        x, y, _ = location.Coordinates
        location.Coordinates = (x, y, elevation)
    quantities = model.by_type("IfcElementQuantity")
    column_quantities = next(row for row in quantities if row.Name == "Qto_ColumnBaseQuantities")
    for row in column_quantities.Quantities:
        if row.Name == "NetVolume":
            row.VolumeValue = .544
        elif row.Name == "GrossSurfaceArea":
            row.AreaValue = 5.76
    for entity in model.by_type("IfcRoot"):
        entity.GlobalId = guid.compress(uuid5(NAMESPACE_URL, f"pmi-speckle-frame/{entity.id()}").hex)
    model.by_type("IfcProject")[0].Name = "PMI Speckle synthetic frame"
    model.header.file_name.name = "speckle_frame.ifc"
    model.write(str(path))


def estimate(source, config, *, project_id, output):
    if config["input_state"] != STATE or config["source_sha256"] != _digest(source):
        raise ValueError("Expected the registered hypothetical IFC4 source.")
    model = ifcopenshell.open(str(source))
    if model.schema != "IFC4" or len(model.by_type("IfcBuildingStorey")) != 1:
        raise ValueError("Expected one IFC4 storey.")
    ifc_elements = model.by_type("IfcElement")
    guids = {obj.GlobalId for obj in ifc_elements}
    if (not guids or len(guids) != len(ifc_elements) or guids != config["elements"].keys()
            or any(obj.is_a() not in {"IfcColumn", "IfcBeam", "IfcSlab"} for obj in ifc_elements)):
        raise ValueError("Unsupported IFC element scope or missing hypothetical inputs.")
    if any(len(obj.ContainedInStructure) != 1
           or not obj.ContainedInStructure[0].RelatingStructure.is_a("IfcBuildingStorey")
           for obj in ifc_elements):
        raise ValueError("Every element requires storey containment.")

    construction_cli(["build-construction", "--geometry", "--input", str(source),
                      "--project-id", project_id, "--output", str(output)])
    bim = _read(output / "import.json")
    construction = _read(output / "construction.json")
    if not bim["is_valid"] or not construction["import_valid"] or construction["graph_issues"]:
        raise ValueError("Strict IFC construction qualification failed.")
    elements = {row["id"]: row for row in bim["elements"]}
    approved = construction["approval_register"]
    if len(approved) != 75 or any(row["status"] != "PENDING" for row in approved):
        raise ValueError("Expected pending Stage 5.2 decisions.")
    references, reference_hash = load_references(REFERENCE)
    if reference_hash != config["reference_sha256"]:
        raise ValueError("Estimation references differ from registration.")
    source_activities = {row["id"]: row for row in construction["activities"]}
    options = {(row["activity_id"], row["bcca_code"]): row for row in construction["catalogue_options"]}
    activities, packages, edges, measurements = [], [], [], []
    geometry = __import__("ifcopenshell.geom", fromlist=["settings"])
    settings = geometry.settings()
    settings.set("use-world-coords", True)
    bounds = []
    operations = {}

    def edge(left, right, rule):
        edges.append({"predecessor_id": left, "successor_id": right, "relation": "FS",
                      "rule_id": rule, "lag_basis": "elapsed", "lag_minutes": 0})

    for package in construction["packages"]:
        element_id, = package["element_ids"]
        element = elements[element_id]
        gid = element["global_id"]
        spec = config["elements"][gid]
        shape = geometry.create_shape(settings, model.by_guid(gid))
        vertices = shape.geometry.verts
        bounds.append([(min(vertices[axis::3]), max(vertices[axis::3])) for axis in range(3)])
        volume, = [row for row in bim["quantities"] if row["element_id"] == element_id
                   and row["basis"] == "represented_body_volume" and row["status"] == "accepted"
                   and row["method"] == "geometry" and row["unit"] == "m3"]
        authored = [row for row in bim["quantities"] if row["element_id"] == element_id
                    and row["basis"] == "net_volume" and row["status"] == "accepted"]
        if any(not isclose(row["value"], volume["value"], abs_tol=1e-8) for row in authored):
            raise ValueError(f"Authored net volume differs from represented volume for {gid}.")
        measurements.append({"global_id": gid, "element_id": element_id,
                             "placed_concrete_m3": volume["value"], "quantity_id": volume["id"]})
        family = package["family"]
        by_item = {source_activities[key]["work_item"]: source_activities[key] for key in package["activity_ids"]}
        expected = {f"{family}-FORM", f"{family}-REBAR", f"{family}-CONC", "CURE", "FRM-STRIP"}
        if family not in {"COL", "BEAM", "SLAB"} or expected != by_item.keys():
            raise ValueError(f"Incomplete supported work package for {gid}.")
        if any(not isinstance(spec[key], str) or not spec[key].strip() for key in
               ("formwork_rule", "reinforcement_boq", "inspection_condition", "curing_condition", "striking_condition")):
            raise ValueError(f"Missing hypothetical evidence for {gid}.")
        scoped = {row["id"] for row in by_item.values()}
        sequence = "cage_first" if family == "COL" else "formwork_first"
        if spec["sequence"] != sequence or not any(
            link["predecessor_id"] in scoped and link["successor_id"] in scoped
            and link["option"] == sequence for link in construction["dependencies"]
        ):
            raise ValueError(f"Unsupported construction sequence for {gid}.")
        base = {"global_id": gid, "element_id": element_id, "package_id": package["id"],
                "input_state": STATE, "eligible_for_real_scheduling": False, "blockers": [],
                "assumption_ref": f"manifest.json#/engineering/elements/{gid}"}
        ids = {}
        for item, row in by_item.items():
            ids[item] = row["id"]
            if item == "CURE":
                continue
            code = config["catalogue"][item]
            choice = options[row["id"], code]
            ref = references[item, code]
            if choice["source_sha256"] != ref["bc3_sha256"]:
                raise ValueError("Catalogue source mismatch.")
            op = "STRIP" if item == "FRM-STRIP" else item.rsplit("-", 1)[1]
            quantity, unit, qty_ids = {
                "CONC": (volume["value"], "m3", [volume["id"]]),
                "REBAR": (spec["reinforcement_kg"], "kg", []),
                "FORM": (spec["formwork_m2"], "m2", []),
                "STRIP": (spec["formwork_m2"], "m2", []),
            }[op]
            if op == "CONC" and config["concrete_specification"] != "HA-25/P/20/XC2":
                raise ValueError("Unsupported concrete specification.")
            _, throughput = _external_resources(ref, config["equipment"], spec)
            result = estimate_operation(quantity, unit, ref, config["crews"][config["crew_by_operation"][op]],
                                        config["equipment"], concurrent_throughput=throughput)
            demand = result["worker_capacity_by_trade"] | result["equipment_capacity_by_class"]
            activities.append({**base, **result, "id": row["id"], "work_item": item, "kind": "productive",
                               "quantity": quantity, "unit": unit, "quantity_ids": qty_ids,
                               "resource_demand": {resource_id(key): val for key, val in demand.items()},
                               "pending_approval_ids": row["pending_approval_ids"]})
        ids["INSPECTION"] = stable_id(package["id"], "milestone-inspection")
        ids["RELEASE"] = stable_id(package["id"], "milestone-elapsed-release")
        holds = (
            ("INSPECTION", "inspection", spec["inspection_elapsed_hours"], {"INSPECTOR": 1}, ["AP-X-INSP-01"]),
            ("CURE", "elapsed_hold", spec["curing_elapsed_hours"], {}, ["AP-W-CURE", "AP-DR07"]),
            ("RELEASE", "elapsed_hold", spec["striking_elapsed_hours_from_pour"], {}, ["AP-DR08"]),
        )
        for name, kind, duration, demands, approvals in holds:
            number(duration, name, positive=True)
            activity = {**base, "id": ids[name], "work_item": name, "kind": kind,
                        "resource_demand": demands, "pending_approval_ids": approvals,
                        "reference_cost_eur": None}
            activity["productive_hours" if demands else "elapsed_hours"] = duration
            activities.append(activity)
        form, bars, pour = (ids[f"{family}-{item}"] for item in ("FORM", "REBAR", "CONC"))
        first, second = (bars, form) if family == "COL" else (form, bars)
        edge(first, second, "DR05" if family == "COL" else "DR06")
        for predecessor in (form, bars):
            edge(predecessor, ids["INSPECTION"], "DR06")
        edge(ids["INSPECTION"], pour, "DR06")
        edge(pour, ids["CURE"], "DR07")
        edge(pour, ids["RELEASE"], "DR08")
        for predecessor in (ids["CURE"], ids["RELEASE"]):
            edge(predecessor, ids["FRM-STRIP"], "DR08")
        operations[gid] = {"POUR": pour, "FORM": form, "STRIP": ids["FRM-STRIP"], "RELEASE": ids["RELEASE"]}
        packages.append({**package, "global_ids": [gid], "activity_ids": list(ids.values())})

    if {row["global_id"] for row in measurements} != guids or len(packages) != len(guids):
        raise ValueError("Stage 5.2 package coverage is incomplete.")
    for left, right in combinations(bounds, 2):
        if all(min(a[1], b[1]) - max(a[0], b[0]) > 1e-8 for a, b in zip(left, right)):
            raise ValueError("Overlapping element bounds require separate qualification.")
    for link in config["support_links"]:
        edge(operations[link["predecessor_gid"]][link["predecessor"]],
             operations[link["successor_gid"]][link["successor"]], "DR09")
    total = sum(row["reference_cost_eur"] or 0 for row in activities)
    return {"source_sha256": config["source_sha256"], "model_version_id": bim["model_version"]["id"],
            "scope": "hypothetical_fixture_only", "eligible_for_real_scheduling": False,
            "eligible_for_controlled_scheduling_input": True, "activities": activities,
            "packages": packages, "dependencies": edges, "element_quantities": measurements,
            "cost": {"currency": "EUR", "total_direct_reference_eur": total}}
