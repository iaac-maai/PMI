"""Validate controlled metadata against the committed registers and fixture records."""

from .fixtures import (
    REFERENCES, ROOT, approvals, read_json, reference_cases, registered_calendar_exception,
)


def check_metadata(problem, require):
    registered = approvals()
    by_id = {row["approval_id"]: row for row in registered}
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

    exceptions = problem.get("fixture_exceptions", [])
    require(isinstance(exceptions, list), "Fixture exceptions must be a list.", "UNVERIFIED_FIXTURE_EXCEPTION")
    if exceptions:
        addendum = read_json(REFERENCES / "resource_contract_R2_addendum.json")
        r0 = [row for row in addendum["R2-5_controlled_fixture_exceptions"] if row["id"].startswith("FX-R0-")]
        if exceptions == r0:
            reference = reference_cases().get(f"R0-{problem.get('tick_minutes', 5)}")
            ids = {task.get("reference_id", task["id"]): task["id"] for task in problem["activities"]}
            reference_ids = {row["id"] for row in reference["activities"]} if reference else set()
            if reference_ids and ids.keys() == reference_ids and any(alias != key for alias, key in ids.items()):
                handover = read_json(ROOT / "research/implementation/stage5_3/scheduling_handover.json")
                reference_ids_match = set(ids.values()) == {row["id"] for row in handover["activities"]}
            else:
                reference_ids_match = bool(reference_ids) and ids == {key: key for key in reference_ids}
            require(reference_ids_match and len(problem["activities"]) == len(reference_ids)
                    and problem["project_start"] == reference["project_start"]
                    and problem["timezone"] == reference["timezone"],
                    "R0 fixture exceptions require the registered activity set and project.",
                    "UNVERIFIED_FIXTURE_EXCEPTION")
        else:
            from .demo import construction_demo

            # The diagnostic annotation is only valid for the known coverage sensitivity.
            matches_demo = any(
                all(problem.get(key) == candidate[key] for key in
                    ("fixture_exceptions", "project_start", "project_calendar", "activities", "reservations"))
                for candidate in (construction_demo(False, coverage_sensitivity=True),
                                  construction_demo(True, coverage_sensitivity=True))
            )
            require(matches_demo, "Unregistered fixture exception metadata.", "UNVERIFIED_FIXTURE_EXCEPTION")
    return registered


def calendar_exception_reason(problem, entry):
    """Return the reason a calendar override cannot be applied."""
    authorization = entry.get("authorization_ref")
    if not isinstance(authorization, str) or not authorization.strip():
        return "MISSING_AUTHORIZATION"
    addendum = read_json(REFERENCES / "resource_contract_R2_addendum.json")
    if entry != registered_calendar_exception(addendum):
        return "UNREGISTERED_AUTHORIZATION"
    reference = reference_cases()["RC06"]
    resource = problem["resources"].get("FERRALLISTA", {})
    calendar = {"timezone": reference["timezone"], "input_state": "hypothetical_fixture", "date_exceptions": [], **reference["resources"]["FERRALLISTA"]["calendar"]}
    actual = next((task for task in problem["activities"] if task["id"] == "N"), {})
    expected = next(task for task in reference["activities"] if task["id"] == "N")
    if (problem["project_start"] != reference["project_start"] or problem["timezone"] != reference["timezone"]
            or problem["project_calendar"] != {"input_state": "hypothetical_fixture", **reference["project_calendar"]} or resource.get("calendar") != calendar
            or any(actual.get(key) != value for key, value in expected.items())):
        return "OUTSIDE_REGISTERED_SCOPE"
    return None

