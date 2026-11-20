"""Regenerate complete C01 benchmark exports using the optimizer CLI."""

import json
from pathlib import Path
import subprocess
import sys

from .fixtures import ROOT


def main():
    destination = Path(__file__).resolve().parent / "benchmark_exports"
    destination.mkdir(exist_ok=True)
    summary = {}
    for label in ("original", "holiday"):
        runs = {}
        for version in ("v1.0", "v1.1"):
            command = [sys.executable, "-B", "-m", "research.implementation.stage5_4b",
                       "--demo", label, "--benchmark-version", version, "--time-limit", "20"]
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            expected_exit = 1 if version == "v1.0" else 0
            if completed.returncode != expected_exit:
                raise RuntimeError(f"{label} {version} returned {completed.returncode}: {completed.stderr}")
            result = json.loads(completed.stdout)
            target = destination / f"{label}_{version}.json"
            target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            fields = ("status", "solver_status", "objective_minutes", "lower_bound_minutes",
                      "optimality_gap_minutes", "optimality_gap", "runtime_seconds", "timestamp_source",
                      "real_project_eligible", "validated", "diagnostic", "completion_local", "cost",
                      "cpm_comparison", "covered_activity_checks", "benchmark_input")
            runs[version] = {key: result[key] for key in fields if key in result}
            if result["validated"]:
                runs[version]["resource_conflict_count"] = len(result["resource_conflicts"])
            runs[version]["export"] = target.relative_to(destination.parent).as_posix()
        summary[label] = runs
    (destination.parent / "benchmark_results.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

