"""Public application orchestration across the IFC and optimization runtimes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _run(stage, argv, root):
    process = subprocess.run([str(value) for value in argv], cwd=root, capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
    if process.returncode:
        raise RuntimeError(f"{stage} exited with {process.returncode}: {process.stderr or process.stdout}")
    return process.stdout


def run_controlled_pipeline(config, *, output, ifc_python, planning_python, tick=5, root=None, ifc4d=False):
    """Execute IFC, construction, estimation, CPM and optimization from an explicit v1 config."""
    root = Path(root or Path.cwd()).resolve()
    if isinstance(config, (str, Path)):
        config = _read(config)
    if config["contract_version"] != "pmi-pipeline-config/1" or tick not in (5, 15):
        raise ValueError("Unsupported pipeline configuration or tick.")
    inputs = {key: (root / config[key]).resolve() for key in ("ifc", "estimation_config", "references")}
    source_hash = _digest(inputs["ifc"])
    if source_hash != config["ifc_sha256"]:
        raise ValueError("IFC hash is outside the registered controlled pipeline.")
    identities = {}
    for name, exe, dependency in (("ifc", ifc_python, "ifcopenshell"), ("planning", planning_python, "ortools")):
        exe = Path(exe).resolve()
        probe = ("import importlib.metadata as m,json,sys;"
                 "print(json.dumps(dict(executable=sys.executable,python=sys.version.split()[0],"
                 f"dependency='{dependency}',version=m.version('{dependency}'))))")
        identities[name] = json.loads(_run(f"{name} runtime probe", [exe, "-B", "-c", probe], root))
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    construction, estimation = output / "construction", output / "estimation"
    _run("IFC and construction", [identities["ifc"]["executable"], "-B", "-m", "pmi_core.cli",
         "build-construction", "--geometry", "--input", inputs["ifc"], "--project-id", config["project_id"],
         "--output", construction], root)
    bim, packages = construction / "import.json", construction / "construction.json"
    _run("engineering estimation", [identities["ifc"]["executable"], "-B", "-m", "pmi_core.estimation",
         "--bim", bim, "--construction", packages, "--config", inputs["estimation_config"],
         "--references", inputs["references"], "--output", estimation], root)
    handover = estimation / "scheduling_handover.json"
    intermediate, evidence = output / "schedule_stage.json", output / "pipeline_evidence.json"
    provenance = {
        "contract_version": "pmi-pipeline-evidence/1", "runtimes": identities,
        "input_sha256": {key: _digest(path) for key, path in inputs.items()},
        "stage_payload_sha256": {key: _digest(path) for key, path in
                                 (("canonical_bim", bim), ("construction", packages), ("estimation", handover))},
        "stage_contracts": {"bim": _read(bim)["contract_version"], "construction": _read(packages)["version"],
                            "estimation": _read(handover)["version"], "cpm": "5.4A",
                            "optimization": "pmi-optimization-result/2"},
    }
    evidence.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    _run("CPM and optimization", [identities["planning"]["executable"], "-B", "-m", config["scheduling_worker"],
         "--handover", handover, "--tick", tick, "--project-id", config["project_id"],
         "--evidence", evidence, "--output", intermediate], root)
    schedule_payload = intermediate.read_bytes()
    result = json.loads(schedule_payload.decode("utf-8-sig"))
    if result.get("contract_version") != "pmi-schedule/1" or result.get("source_ifc_sha256") != source_hash:
        raise ValueError("Schedule contract or provenance mismatch.")
    if result["model_version_id"] != _read(handover)["model_version_id"]:
        raise ValueError("Schedule and engineering handover model identities differ.")
    target = output / "schedule.json"
    intermediate.replace(target)
    if ifc4d:
        schedule_digest = hashlib.sha256(schedule_payload).hexdigest()
        provenance["stage_payload_sha256"]["schedule"] = schedule_digest
        evidence.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
        export = ("import sys; from pmi_core.adapters.ifc4d import _export_live; "
                  "_export_live(*sys.argv[1:])")
        _run("controlled IFC4D export", [identities["ifc"]["executable"], "-B", "-c", export,
             inputs["ifc"], target, output / "ifc4d", schedule_digest], root)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "output", "ifc-python", "planning-python"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--tick", choices=(5, 15), type=int, default=5)
    parser.add_argument("--ifc4d", action="store_true", help="Export verified controlled R0 IFC4D.")
    args = parser.parse_args(argv)
    try:
        result = run_controlled_pipeline(args.config, output=args.output, ifc_python=args.ifc_python,
                                         planning_python=args.planning_python, tick=args.tick, ifc4d=args.ifc4d)
    except (KeyError, OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps({"output": str(args.output / "schedule.json"), "proof": result["proof"]}, indent=2))
    return 0 if result["internal_timestamp_validated"] and result["proof"]["schedule_scope"] == "complete_project" else 1


if __name__ == "__main__":
    raise SystemExit(main())
