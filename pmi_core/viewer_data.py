"""Presentation contract for CPM and CP-SAT comparison and model selection."""


def build_viewer_data(schedule, evidence):
    recovered = evidence["activities"]
    element_activities = {gid: [] for gid in evidence["source_element_global_ids"]}
    activities = {}
    for row in schedule["activities"]:
        key = row["activity_id"]
        verified = recovered[key]
        gid = verified["element_global_id"]
        element_activities[gid].append(key)
        activities[key] = {
            "label": row["reference_id"],
            "kind": row["kind"],
            "package_id": verified["work_package_id"],
            "ifc_task_global_id": verified["task_global_id"],
            "element_global_ids": [gid],
            "cpm": row["baseline"],
            "cp_sat": row["optimized"],
            "input_state": row["input_state"],
            "approval_status": "PENDING",
            "approval_ids": row["approval_ids"],
        }
    return {
        "contract_version": "pmi-ifc4d-viewer/1",
        "model": {
            "uri": "scheduled.ifc",
            "model_version_id": schedule["model_version_id"],
            "sha256": evidence["output_ifc_sha256"],
        },
        "activities_by_id": activities,
        "activity_ids_by_element_global_id": element_activities,
        "packages": schedule["work_packages"],
        "dependencies": evidence["dependencies"],
        "status": evidence["provenance"],
        "restriction": evidence["restriction"],
    }
