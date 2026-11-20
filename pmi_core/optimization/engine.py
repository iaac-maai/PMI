"""Solver execution and primary proof reporting."""
from math import ceil, isfinite
from zoneinfo import ZoneInfoNotFoundError
from ortools.sat.python import cp_model
from pmi_core.scheduling.calendar import SchedulingError
from .schemas import require
from .preparation import prepare
from .diagnostics import coverage_contradiction, _without_deadline_diagnostic
from .model import build_model
from .results import serialize
from .validation import validate

INFEASIBLE = {"IMPOSSIBLE_CREW", "NO_FIT", "INFEASIBLE_DEADLINE", "HORIZON_EXHAUSTED"}
def solve(problem, *, registry, time_limit=10.0, _probe_horizon=True):
    """Return a verified controlled schedule or a structured diagnostic."""
    from .registry import check_metadata

    result = {"contract_version": "pmi-optimization-result/2", "schedule_scope": None,
              "project_makespan_minutes": None, "makespan_by_scope_minutes": {}, "timestamp_source": None, "secondary_solver_status": None,
              "primary_runtime_seconds": 0.0, "secondary_runtime_seconds": 0.0,
              "diagnostic_runtime_seconds": 0.0, "optimality_gap_minutes": None,
              "ignored_calendar_exceptions": [], "solver_status": None, "solver_scope": "controlled", "objective_minutes": None, "lower_bound_minutes": None,
              "optimality_gap": None, "runtime_seconds": 0.0, "real_project_eligible": False,
              "activities": [], "validated": False}
    try:
        require(isfinite(time_limit) and time_limit > 0, "Time limit must be positive.")
        # Check the scope before any metadata can be echoed back.
        require(problem["scope"] == "hypothetical_fixture_only", "Controlled inputs only.")
        registered = check_metadata(problem, registry, require)
        prepared = prepare(problem, registry=registry, ignored_exceptions=result["ignored_calendar_exceptions"])
        result["pending_approvals"] = registered
    except SchedulingError as error:
        return dict(result, status="INFEASIBLE" if error.code in INFEASIBLE else "MODEL_INVALID",
                    diagnostic={"code": error.code, "message": str(error), **error.details})
    except (KeyError, TypeError, ValueError, AttributeError, ZoneInfoNotFoundError, OverflowError) as error:
        return dict(result, status="MODEL_INVALID",
                    diagnostic={"code": "MISSING_INPUT" if isinstance(error, KeyError) else "MODEL_INVALID",
                                "message": str(error)})
    (zone, origin, limit, tick, tasks, capacities, domains, durations, _,
     links, deadlines, lower, advanced) = prepared
    recorded, strength, conditional, blocked, reservations, supplies, splits, profiles = advanced
    contradiction = coverage_contradiction(reservations, links, durations)
    if contradiction:
        return dict(result, status="INFEASIBLE", diagnostic=contradiction)
    model, starts, ends, pieces, reservation_ends, makespan, labels = build_model(prepared)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 8 if len(tasks) >= 40 and not labels else 1
    status = solver.solve(model)
    runtime = solver.wall_time
    result.update(status=solver.status_name(status), solver_status=solver.status_name(status),
                  runtime_seconds=runtime, primary_runtime_seconds=runtime)
    if status == cp_model.INFEASIBLE:
        core = [labels[index] for index in solver.sufficient_assumptions_for_infeasibility()]
        if core:
            # A core need not be minimal and can contain deadlines even if the base is infeasible.
            model.clear_assumptions()
            check = cp_model.CpSolver()
            check.parameters.max_time_in_seconds = max(0.001, time_limit - runtime)
            base = check.solve(model)
            result["runtime_seconds"] += check.wall_time
            result["diagnostic_runtime_seconds"] += check.wall_time
            if base in (cp_model.FEASIBLE, cp_model.OPTIMAL):
                result["diagnostic"] = {"code": "INFEASIBLE_DEADLINE", "deadlines": core}
            else:
                result["diagnostic"] = {"code": "INFEASIBLE", "deadline_candidates": core,
                                        "without_deadlines_status": check.status_name(base)}
        else:
            budget = time_limit - runtime if _probe_horizon else 0
            diagnostic, spent = _without_deadline_diagnostic(
                problem, zone, origin, limit, budget,
                lambda candidate, seconds: solve(candidate, registry=registry, time_limit=seconds, _probe_horizon=False))
            result["diagnostic"] = diagnostic
            result["runtime_seconds"] += spent
            result["diagnostic_runtime_seconds"] += spent
        return result
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if status == cp_model.UNKNOWN:
            result["lower_bound_minutes"] = max(lower, ceil(solver.best_objective_bound)) * tick
        return result
    objective = solver.value(makespan)
    bound = objective if status == cp_model.OPTIMAL else max(lower, ceil(solver.best_objective_bound))
    result["timestamp_source"] = "primary"
    # Choose early dates within the proven makespan, using only the remaining solve budget.
    if status == cp_model.OPTIMAL and time_limit > runtime and len(tasks) < 40 and _probe_horizon:
        model.add(makespan == objective)
        model.minimize(sum(starts.values()))
        tie_break = cp_model.CpSolver()
        tie_break.parameters.num_search_workers = 1
        tie_break.parameters.max_time_in_seconds = time_limit - runtime
        tie_status = tie_break.solve(model)
        result["runtime_seconds"] += tie_break.wall_time
        result["secondary_runtime_seconds"] = tie_break.wall_time
        result["secondary_solver_status"] = tie_break.status_name(tie_status)
        if tie_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            solver = tie_break
            result["timestamp_source"] = "secondary"
    return serialize(problem, result, prepared, solver, starts, ends, pieces, reservation_ends,
                     objective, bound, registry)
