"""Command-line entry point. Run from the repository root."""

import argparse
import json
from hashlib import sha256
from pathlib import Path

from .demo import benchmark_path, construction_demo, cpm_comparison
from .engine import solve
from .fixtures import REFERENCES, frozen_r0, reference_cases, normalize_reference


def unique_keys(pairs):
    values = {}
    for key, value in pairs:
        if key in values:
            raise ValueError(f"Duplicate JSON key: {key!r}.")
        values[key] = value
    return values


def main():
    cases = reference_cases()
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--case", choices=sorted(cases.keys() - {"DEMO-H1"}))
    source.add_argument("--frozen-r0", type=int, choices=(5, 15))
    source.add_argument("--demo", choices=("original", "holiday"), help="Frozen construction demonstration")
    parser.add_argument("--benchmark-version", choices=("v1.0", "v1.1"), default=None)
    parser.add_argument("--coverage-sensitivity", action="store_true",
                        help="Diagnostic only. Exclude cage-first predecessor work from reservation coverage")
    source.add_argument("--input", type=Path, help="Normalized controlled JSON")
    parser.add_argument("--time-limit", type=float, default=10.0)
    args = parser.parse_args()
    if args.benchmark_version and not args.demo:
        parser.error("--benchmark-version requires --demo")
    if args.coverage_sensitivity and args.benchmark_version == "v1.1":
        parser.error("--coverage-sensitivity applies only to v1.0")
    if args.coverage_sensitivity and not args.demo:
        parser.error("--coverage-sensitivity requires --demo")
    if args.case:
        problem = normalize_reference(cases[args.case])
    elif args.frozen_r0:
        problem = frozen_r0(args.frozen_r0)
    elif args.demo:
        version = args.benchmark_version or ("v1.0" if args.coverage_sensitivity else "v1.1")
        problem = construction_demo(args.demo == "holiday", version=version,
                                    coverage_sensitivity=args.coverage_sensitivity)
    else:
        try:
            problem = json.loads(args.input.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_keys)
        except (ValueError, OSError) as error:
            print(json.dumps({"status": "MODEL_INVALID", "solver_status": None, "activities": [],
                              "real_project_eligible": False,
                              "diagnostic": {"code": "INVALID_JSON_INPUT", "message": str(error)}}))
            return 1
    result = solve(problem, time_limit=args.time_limit)
    if args.demo:
        result["cpm_comparison"] = cpm_comparison(problem)
        path = benchmark_path(args.demo == "holiday", version)
        result["benchmark_input"] = {"version": version, "path": path.relative_to(REFERENCES).as_posix(),
                                     "sha256": sha256(path.read_bytes()).hexdigest(),
                                     "coverage_sensitivity": args.coverage_sensitivity}
    print(json.dumps(result, indent=2))
    return 0 if result["validated"] and result["status"] in {"OPTIMAL", "FEASIBLE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

