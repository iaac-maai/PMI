"""Read one pinned Speckle version and verify its imported IFC identities."""
import argparse
import json
import os
from pathlib import Path
import re

HOST = "https://app.speckle.systems"
GUID = re.compile(r"[0-3][0-9A-Za-z_$]{21}")


def identity_map(objects, expected):
    """Match explicit IFC properties; keep application and viewer IDs distinct."""
    result = {}
    applications = set()
    for obj in objects:
        properties = obj.properties
        direct = properties.get("IFC GUID")
        nested = properties.get("IFC Attributes.GlobalId")
        if isinstance(properties.get("IFC Attributes"), dict):
            nested = nested or properties["IFC Attributes"].get("GlobalId")
        if direct and nested and direct != nested:
            raise ValueError("Conflicting IFC GlobalId properties.")
        guid = direct or nested
        if guid not in expected:
            continue
        application_id = obj.application_id
        if guid in result or not application_id or application_id in applications:
            raise ValueError("Ambiguous IFC to Speckle identity.")
        applications.add(application_id)
        result[guid] = {"speckle_application_id": application_id, "viewer_object_id": None}
    if result.keys() != expected:
        raise ValueError(f"Missing {len(expected - result.keys())} registered IFC GlobalIds.")
    return result


def inspect_version(project, model, version, expected):
    from specklepy.api import operations
    from specklepy.api.client import SpeckleClient

    token = os.environ.get("PMI_SPECKLE_TOKEN")
    if not token:
        raise ValueError("PMI_SPECKLE_TOKEN is not configured locally.")
    if not all(re.fullmatch("[a-zA-Z0-9_-]{1,100}", value) for value in (project, model, version)):
        raise ValueError("Invalid Speckle identifiers.")
    client = SpeckleClient(host=HOST)
    client.authenticate_with_token(token)
    entry = client.version.get(version_id=version, project_id=project)
    if entry.referenced_object != f"bundle.{project}.{model}.{version}":
        raise ValueError("Expected an IFC upload bundle for this exact project/model/version.")
    with operations.receive3(client.account, project, model, version, include_geometry=False, mark_received=False) as received:
        return identity_map(received.objects, expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "model", "version"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--ifc-identities", required=True, type=Path,
                        help="Local qualification JSON containing source_ifc_sha256 and global_ids.")
    args = parser.parse_args()
    try:
        evidence = json.loads(args.ifc_identities.read_bytes())
        digest = evidence["source_ifc_sha256"]
        ids = evidence["global_ids"]
        expected = set(ids)
        if (not re.fullmatch("[a-f0-9]{64}", digest) or not expected or len(ids) != len(expected)
                or not all(GUID.fullmatch(key) for key in expected)):
            raise ValueError("Invalid local IFC qualification report.")
        mapping = inspect_version(args.project, args.model, args.version, expected)
        print(json.dumps({"host": HOST, "project": args.project, "model": args.model,
                          "version": args.version, "source_ifc_sha256": digest,
                          "mapping": mapping}, indent=2))
    except Exception as error:
        # SDK transport diagnostics may contain credentials or presigned URLs.
        message = str(error) if type(error) is ValueError and str(error).startswith(
            ("PMI_", "Invalid ", "Expected ", "Missing ", "Ambiguous ", "Conflicting ")) else type(error).__name__
        parser.exit(1, f"Speckle inspection refused: {message}\n")


if __name__ == "__main__":
    main()
