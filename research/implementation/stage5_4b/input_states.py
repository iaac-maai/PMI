"""Audit provenance on the normalized scheduling entities."""

from .fixtures import REFERENCES, read_json


def audit_input_states(problem, require):
    registered = read_json(REFERENCES / "resource_contract.json")["enumerations"]["input_state"]["values"]

    def audit(row, path, *, field="input_state", condition=False, context=None):
        require(field in row, f"Missing {field} at {path}.", "MISSING_INPUT")
        state = row[field]
        require(state in registered, f"Invalid {field} at {path}: {state!r}.", "INVALID_INPUT_STATE")
        require(state != "engineer_approved", f"Unverified engineering approval at {path}.", "UNVERIFIED_APPROVAL")
        require(state != "missing" or condition, f"Missing scheduling input at {path}.", "MISSING_INPUT")
        if state in {"user_provided_project", "independently_measured"}:
            evidence = row.get("evidence_ref") or (context or {}).get("evidence_ref")
            require(isinstance(evidence, str) and evidence.strip(),
                    f"Missing evidence reference at {path}.", "MISSING_INPUT")

    def calendar_state(row, path):
        audit(row, path)
        require(isinstance(row.get("date_exceptions"), list),
                f"Missing date_exceptions list at {path}.", "MISSING_INPUT")

    calendar_state(problem["project_calendar"], "project_calendar")
    for rid, row in problem["resources"].items():
        audit(row, f"resources.{rid}")
        require("evidence_ref" in row, f"Missing resource evidence field at resources.{rid}.", "MISSING_INPUT")
        require(row["evidence_ref"] is None or (isinstance(row["evidence_ref"], str) and row["evidence_ref"].strip()),
                f"Invalid resource evidence reference at resources.{rid}.", "INVALID_INPUT_STATE")
        if isinstance(row.get("calendar"), dict):
            calendar_state(row["calendar"], f"resources.{rid}.calendar")
    for task in problem["activities"]:
        key = task["id"]
        audit(task, f"activities.{key}")
        if "crew_mode" in task:
            audit(task, f"activities.{key}.crew_mode", field="crew_mode_input_state")
        if isinstance(task.get("split"), dict):
            audit(task["split"], f"activities.{key}.split", context=task)
    for row in problem.get("reservations", []):
        key = row["reservation_id"]
        audit(row, f"reservations.{key}")
        audit(row["release_condition"], f"reservations.{key}.release_condition", context=row)
    for kind in ("inspection_pass_events", "strength_events", "release_events"):
        for row in problem.get(kind, []):
            # Missing evidence may yield a declared projection, but it cannot be a pass.
            projected_missing = kind != "release_events" and row["status"] in {"missing", "pending_result"}
            audit(row, f"{kind}.{row['event_id']}", condition=projected_missing)
    for row in problem.get("calendar_exceptions", []):
        # A missing authorization still falls back to the default calendar.
        audit(row, f"calendar_exceptions.{row.get('exception_id')}",
              condition=not row.get("authorization_ref"))

