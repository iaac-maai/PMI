"""Validate controlled metadata against the committed registers and fixture records."""

from .fixtures import (
    REFERENCES, ROOT, approvals, read_json, reference_cases, registered_calendar_exception,
)


from pmi_core.optimization.registry import ControlledRegistry


def registry():
    return ControlledRegistry(tuple(approvals()), fixture_metadata_allowed, calendar_exception_reason)


def fixture_metadata_allowed(problem):
    exceptions = problem.get("fixture_exceptions", [])
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
            return (reference_ids_match and len(problem["activities"]) == len(reference_ids)
                    and problem["project_start"] == reference["project_start"]
                    and problem["timezone"] == reference["timezone"])
        else:
            from .demo import construction_demo

            # The diagnostic annotation is only valid for the known coverage sensitivity.
            matches_demo = any(
                all(problem.get(key) == candidate[key] for key in
                    ("fixture_exceptions", "project_start", "project_calendar", "activities", "reservations"))
                for candidate in (construction_demo(False, coverage_sensitivity=True),
                                  construction_demo(True, coverage_sensitivity=True))
            )
            return matches_demo
    return True


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

