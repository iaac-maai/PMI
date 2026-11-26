"""Loopback visualization of a newly generated controlled milestone bundle."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import ifcopenshell
import ifcopenshell.geom
import plotly

from pmi_core.application import _digest, _read, _run
from .application import ROOT, MODULE, SOURCE_SHA


def workspace(bundle):
    provenance = _read(bundle / "provenance.json")
    for file, digest in (("source.ifc", SOURCE_SHA), ("scheduled.ifc", provenance["ifc4d_sha256"]),
                         ("viewer.json", provenance["viewer_sha256"]),
                         ("schedule.json", provenance["schedule_sha256"])):
        if _digest(bundle / file) != digest:
            raise ValueError(f"Fresh bundle digest mismatch: {file}.")
    data = _read(bundle / "viewer.json")
    schedule = _read(bundle / "schedule.json")
    if (data["model"]["sha256"] != provenance["ifc4d_sha256"]
            or data["status"]["ScheduleSha256"] != provenance["schedule_sha256"]
            or data["status"]["ApprovalStatus"] != "PENDING"
            or data["status"]["PendingApprovalCount"] != 88
            or data["status"]["RealProjectEligible"] is not False):
        raise ValueError("Unexpected viewer provenance or approval status.")
    model = ifcopenshell.open(str(bundle / "scheduled.ifc"))
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    elements = {}
    for element in model.by_type("IfcElement"):
        shape = ifcopenshell.geom.create_shape(settings, element)
        vertices, faces = shape.geometry.verts, shape.geometry.faces
        elements[element.GlobalId] = {
            "name": element.Name, "ifc_class": element.is_a(),
            "vertices": list(zip(vertices[::3], vertices[1::3], vertices[2::3])),
            "faces": list(zip(faces[::3], faces[1::3], faces[2::3])),
        }
    if elements.keys() != data["activity_ids_by_element_global_id"].keys():
        raise ValueError("Viewer geometry and schedule links differ.")
    proof = {key: schedule["proof"][key] for key in ("status", "project_makespan_minutes", "lower_bound_minutes")}
    identical = all((row["cpm"]["start"], row["cpm"]["finish"]) ==
                    (row["cp_sat"]["start"], row["cp_sat"]["finish"])
                    for row in data["activities_by_id"].values())
    return {"contract_version": "pmi-r0-prototype/1", "viewer": data, "elements": elements,
            "proof": proof, "origin": "Fresh controlled IFC run · Speckle link pending",
            "comparison": ("CPM and CP-SAT dates coincide in this controlled run." if identical
                           else "Switch between the CPM baseline and the resource-constrained schedule.")}


def build_server(data, port):
    assets = ROOT / "research/implementation/stage5_4d"
    html = (assets / "index.html").read_text(encoding="utf-8-sig")
    html = html.replace("R0 construction sequence", "Controlled frame programme")
    html = html.replace("R0 Construction Sequence", "Controlled Frame Programme")
    html = html.replace("CPM and CP-SAT dates coincide in this R0 fixture.", data["comparison"])
    routes = {
        "/": ("text/html; charset=utf-8", html.encode()),
        "/style.css": ("text/css; charset=utf-8", (assets / "style.css").read_bytes()),
        "/app.js": ("text/javascript; charset=utf-8", (assets / "app.js").read_bytes()),
        "/plotly.js": ("text/javascript; charset=utf-8",
                       (Path(plotly.__file__).parent / "package_data/plotly.min.js").read_bytes()),
        "/data.json": ("application/json", json.dumps(data).encode()),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in routes:
                self.send_error(404)
                return
            kind, payload = routes[self.path]
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8771)
    args = parser.parse_args()
    try:
        with TemporaryDirectory(prefix="pmi-speckle-viewer-") as temporary:
            bundle = Path(temporary) / "bundle"
            _run("fresh milestone application run", [ROOT / ".venv-planning/Scripts/python.exe", "-B", "-m",
                                                      f"{MODULE}.application", "--output", bundle], ROOT)
            data = workspace(bundle)
        with build_server(data, args.port) as server:
            print(f"Controlled PMI viewer at http://127.0.0.1:{server.server_port}", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
