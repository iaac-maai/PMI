"""Controlled R0 handover adapter for the scheduling interpreter."""
import argparse
import json
from pathlib import Path

from pmi_core.schedule_result import schedule_result
from research.implementation.stage5_4b.engine import solve
from research.implementation.stage5_4b.fixtures import frozen_r0, read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("handover", "evidence", "output"):
        parser.add_argument(f"--{key}", required=True, type=Path)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--tick", required=True, type=int, choices=(5, 15))
    args = parser.parse_args()
    baseline = {}
    handover = read_json(args.handover)
    problem = frozen_r0(args.tick, handover=handover, baseline_output=baseline)
    result = schedule_result(optimized=solve(problem), baseline=baseline,
                             project_id=args.project_id, provenance=read_json(args.evidence),
                             engineering={row["id"]: row for row in handover["activities"]})
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
