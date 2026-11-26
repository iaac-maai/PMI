"""Run the registered Speckle milestone IFC through isolated PMI runtimes."""
import argparse
import csv
import json
from pathlib import Path
import tempfile

from pmi_core.application import _digest, _read, _run

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MODULE = "research.implementation.speckle_milestone"
SOURCE = HERE / "speckle_frame.ifc"
CONFIG = HERE / "manifest.json"
SOURCE_SHA = "d06a3a78649e0e401be7faeaf148321a317dcfb8aa11ba13211a38fc2680b467"
MANIFEST_SHA = "56548a7559656c8885dbbee4bbeea18ea73a768504cbd4443fb487a3b0468379"
APPROVALS = {
    "research/validation/engineering_approval_review/priority_approval_register.csv":
        "d86a26cea516c10a38d97c5d82b5ca03d4af940f01a9bdcdd359bdac3111ab23",
    "research/validation/stage5_4a_independent_verification/engineering_approval_addendum.csv":
        "fdc1e1ceac93b45adbf74ad06c724abcc83cffed8dc6812a6bbf71e81df92a90",
}


def approvals():
    rows = []
    for path, digest in APPROVALS.items():
        path = ROOT / path
        if _digest(path) != digest:
            raise ValueError("Pending approval source hash differs.")
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows.extend(csv.DictReader(stream))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ifc-python", type=Path, default=ROOT / ".venv/Scripts/python.exe")
    parser.add_argument("--planning-python", type=Path, default=ROOT / ".venv-planning/Scripts/python.exe")
    args = parser.parse_args()
    output = args.output.resolve()
    try:
        if output.exists() or _digest(SOURCE) != SOURCE_SHA:
            raise ValueError("Expected a fresh output and the registered IFC source.")
        config = _read(CONFIG)
        with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
            bundle = Path(temporary) / "bundle"
            bundle.mkdir()
            source = bundle / "source.ifc"
            source.write_bytes(SOURCE.read_bytes())
            manifest = bundle / "manifest.json"
            manifest.write_bytes(CONFIG.read_bytes())
            if _digest(source) != SOURCE_SHA or _digest(manifest) != MANIFEST_SHA:
                raise ValueError("Registered input snapshot differs.")
            handover = bundle / "engineering_handover.json"
            script = ("import sys; from pathlib import Path; "
                      f"from {MODULE}.engineering import estimate; "
                      "from pmi_core.application import _read; "
                      "import json; s,m,o,h=map(Path,sys.argv[1:]); c=_read(m); "
                      "h.write_text(json.dumps(estimate(s,c['engineering'],project_id=c['project_id'],output=o),"
                      " ensure_ascii=False,indent=2),encoding='utf-8')")
            _run("controlled IFC estimation", [args.ifc_python.resolve(), "-B", "-c", script,
                 source, manifest, bundle / "construction", handover], ROOT)
            measured = _read(handover)
            provenance = {"source_ifc_sha256": SOURCE_SHA, "manifest_sha256": MANIFEST_SHA,
                          "handover_sha256": _digest(handover), "approval_sha256": APPROVALS,
                          "canonical_bim_sha256": _digest(bundle / "construction/import.json"),
                          "construction_sha256": _digest(bundle / "construction/construction.json")}
            (bundle / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
            (bundle / "ifc_identities.json").write_text(json.dumps({
                "source_ifc_sha256": SOURCE_SHA,
                "global_ids": sorted(row["global_id"] for row in measured["element_quantities"]),
            }, indent=2), encoding="utf-8")
            script = ("import sys,json; from pathlib import Path; "
                      f"from {MODULE}.application import approvals, SOURCE_SHA; "
                      f"from {MODULE}.worker import schedule_handover; "
                      "from pmi_core.application import _read; "
                      "d=Path(sys.argv[1]); c=_read(d/'manifest.json'); "
                      "r=schedule_handover(_read(d/'engineering_handover.json'),c['scheduling'],"
                      "source_sha256=SOURCE_SHA,approvals=approvals(),project_id=c['project_id'],"
                      "provenance=_read(d/'provenance.json')); "
                      "(d/'schedule.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')")
            _run("controlled CPM and CP-SAT", [args.planning_python.resolve(), "-B", "-c", script, bundle], ROOT)
            schedule_digest = _digest(bundle / "schedule.json")
            script = ("import sys; "
                      f"from {MODULE}.ifc4d import export_in_run; "
                      "export_in_run(sys.argv[1], source_digest=sys.argv[2], schedule_digest=sys.argv[3])")
            _run("controlled IFC4D round trip", [args.ifc_python.resolve(), "-B", "-c", script,
                 bundle, SOURCE_SHA, schedule_digest], ROOT)
            provenance.update(schedule_sha256=schedule_digest, ifc4d_sha256=_digest(bundle / "scheduled.ifc"),
                              viewer_sha256=_digest(bundle / "viewer.json"),
                              round_trip_sha256=_digest(bundle / "round_trip.json"))
            (bundle / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
            bundle.rename(output)
        print(output)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
