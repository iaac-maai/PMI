"""Serve a verified R0 prototype on loopback."""
import argparse
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import ifcopenshell
import ifcopenshell.geom
import plotly

from pmi_core.adapters.ifc4d import _export_live, export_controlled_ifc4d

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / "research/implementation/stage5_2/controlled_frame.ifc"
SCHEDULES = ROOT / "research/implementation/stage5_4b_integration"
ELEMENTS = {"1jDfy2_jTRueAw6f5fc3Ev", "24tlOXIsvMQfyRLiqh6fZt", "3wOB$MtWLSz8SJNgW3VJvy"}
PROOF_FIELDS = ("status", "project_makespan_minutes", "lower_bound_minutes", "schedule_scope")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def meshes(path):
    model = ifcopenshell.open(str(path))
    elements = model.by_type("IfcElement")
    require(len(elements) == 3 and {element.GlobalId for element in elements} == ELEMENTS,
            "Expected exactly the three registered R0 elements.")
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    result = {}
    for element in elements:
        shape = ifcopenshell.geom.create_shape(settings, element)
        geometry = shape.geometry
        vertices, faces = geometry.verts, geometry.faces
        result[element.GlobalId] = {
            "name": element.Name, "ifc_class": element.is_a(),
            "vertices": list(zip(vertices[::3], vertices[1::3], vertices[2::3])),
            "faces": list(zip(faces[::3], faces[1::3], faces[2::3])),
        }
    return result


def load_workspace(*, tick=5, run_dir=None):
    """Rebuild the accepted bundle before exposing any data to the browser."""
    with TemporaryDirectory(prefix="pmi-r0-viewer-") as temp:
        temp = Path(temp)
        expected = temp / "ifc4d"
        if run_dir is None:
            require(tick in (5, 15), "Only registered 5- and 15-minute R0 replays are supported.")
            schedule_path = SCHEDULES / f"r0_{tick}_schedule.json"
            payload = schedule_path.read_bytes()
            snapshot = temp / "schedule.json"
            snapshot.write_bytes(payload)
            export_controlled_ifc4d(SOURCE, snapshot, expected)
            origin = f"Registered R0 replay · {tick}-minute resolution"
        else:
            run_dir = Path(run_dir)
            snapshot = temp / "schedule.json"
            payload = (run_dir / "schedule.json").read_bytes()
            snapshot.write_bytes(payload)
            pipeline = json.loads((run_dir / "pipeline_evidence.json").read_bytes())
            evidence = json.loads(payload)["evidence"]
            digest = pipeline["stage_payload_sha256"].pop("schedule")
            require(digest == sha256(payload).hexdigest() and pipeline == evidence,
                    "Schedule and application pipeline evidence disagree.")
            _export_live(SOURCE, snapshot, expected, digest)
            origin = "Authenticated R0 application run"
            for name in ("scheduled.ifc", "viewer.json", "round_trip.json"):
                require((run_dir / "ifc4d" / name).read_bytes() == (expected / name).read_bytes(),
                        f"Application bundle differs from the authenticated export: {name}.")

        schedule = json.loads(payload)
        viewer = json.loads((expected / "viewer.json").read_bytes())
        ifc = expected / "scheduled.ifc"
        require(viewer["model"]["sha256"] == sha256(ifc.read_bytes()).hexdigest(),
                "Viewer IFC digest does not match.")
        approvals = schedule["pending_approvals"]
        require(len(approvals) == 88 and all(row["status"] == "PENDING" for row in approvals)
                and schedule["real_project_eligible"] is False, "Unsupported engineering approval state.")
        return {
            "contract_version": "pmi-r0-prototype/1",
            "viewer": viewer, "elements": meshes(ifc), "origin": origin,
            "proof": {key: schedule["proof"][key] for key in PROOF_FIELDS},
        }


def build_server(workspace, port):
    plotly_js = Path(plotly.__file__).parent / "package_data/plotly.min.js"
    routes = {
        "/": ("text/html; charset=utf-8", (HERE / "index.html").read_bytes()),
        "/style.css": ("text/css; charset=utf-8", (HERE / "style.css").read_bytes()),
        "/app.js": ("text/javascript; charset=utf-8", (HERE / "app.js").read_bytes()),
        "/plotly.js": ("text/javascript; charset=utf-8", plotly_js.read_bytes()),
        "/data.json": ("application/json", json.dumps(workspace).encode()),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            resource = routes.get(self.path)
            if resource is None:
                self.send_error(404)
                return
            mime, payload = resource
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--tick", type=int, choices=(5, 15), default=5)
    source.add_argument("--run-dir", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        workspace = load_workspace(tick=args.tick, run_dir=args.run_dir)
        with build_server(workspace, args.port) as server:
            print(f"PMI R0 prototype at http://127.0.0.1:{server.server_port}", flush=True)
            server.serve_forever()
    except (OSError, KeyError, ValueError, RuntimeError, TypeError) as error:
        parser.exit(1, f"R0 prototype refused to start: {error}\n")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
