"""Injected controlled scheduling authority, with no fixture path dependencies."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable


def no_exceptions(problem):
    return not problem.get("fixture_exceptions")


def unregistered_calendar(problem, entry):
    return "MISSING_AUTHORIZATION" if not entry.get("authorization_ref") else "UNREGISTERED_AUTHORIZATION"


@dataclass(frozen=True)
class ControlledRegistry:
    """Trusted application configuration. Do not construct it from solver request JSON."""

    pending_approvals: tuple
    fixture_metadata_allowed: Callable = no_exceptions
    calendar_exception_reason: Callable = unregistered_calendar


def check_metadata(problem, registry, require):
    registered = list(registry.pending_approvals)
    by_id = {row["approval_id"]: row for row in registered}
    require(len(registered) == len(by_id) == 88 and all(row["status"] == "PENDING" for row in registered),
            "Controlled registry must hold 88 unique PENDING approvals.", "UNVERIFIED_APPROVAL")
    if "pending_approvals" in problem:
        supplied = problem["pending_approvals"]
        require(isinstance(supplied, list) and len(supplied) == len(registered)
                and {row["approval_id"]: row for row in supplied} == by_id,
                "Approval metadata must match all 88 registered PENDING rows.", "UNVERIFIED_APPROVAL")
    for task in problem["activities"]:
        require(all(key in by_id for key in task.get("pending_approval_ids", [])),
                f"Unregistered pending approval on {task['id']}.", "UNVERIFIED_APPROVAL")
        if "reservation_approval_ref" in task:
            require(task["reservation_approval_ref"] in by_id,
                    f"Unregistered reservation approval on {task['id']}.", "UNVERIFIED_APPROVAL")
    for key, resource in problem["resources"].items():
        if resource.get("approval_ref") is not None:
            require(resource["approval_ref"] in by_id,
                    f"Unregistered resource approval on {key}.", "UNVERIFIED_APPROVAL")

    require(isinstance(problem.get("fixture_exceptions", []), list) and registry.fixture_metadata_allowed(problem),
            "Unregistered fixture exception metadata.", "UNVERIFIED_FIXTURE_EXCEPTION")
    return deepcopy(registered)
