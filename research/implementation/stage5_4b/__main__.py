"""Command-line entry point. Run from the repository root."""

import argparse
import json
from pathlib import Path

from .demo import construction_demo, cpm_comparison
from .engine import solve
from .fixtures import frozen_r0, read_json, reference_cases, normalize_reference


def main():
    cases = reference_cases()
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--case", choices=sorted(cases.keys() - {"DEMO-H1"}))
    source.add_argument("--frozen-r0", type=int, choices=(5, 15))
    source.add_argument("--demo", choices=("original", "holiday"), help="Frozen construction demonstration")
    parser.add_argument("--coverage-sensitivity", action="store_true",
                        help="Diagnostic only. Exclude cage-first predecessor work from reservation coverage")
    source.add_argument("--input", type=Path, help="Normalized controlled JSON")
    parser.add_argument("--time-limit", type=float, default=10.0)
    args = parser.parse_args()
    if args.coverage_sensitivity and not args.demo:
        parser.error("--coverage-sensitivity requires --demo")
    if args.case:
        problem = normalize_reference(cases[args.case])
    elif args.frozen_r0:
        problem = frozen_r0(args.frozen_r0)
    elif args.demo:
        problem = construction_demo(args.demo == "holiday", coverage_sensitivity=args.coverage_sensitivity)
    else:
        problem = read_json(args.input)
    result = solve(problem, time_limit=args.time_limit)
    if args.demo:
        result["cpm_comparison"] = cpm_comparison(problem)
    print(json.dumps(result, indent=2))
    return 0 if result["validated"] and result["status"] in {"OPTIMAL", "FEASIBLE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

