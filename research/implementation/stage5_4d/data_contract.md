# Stage 5.4D frontend data contract

The loopback server exposes a single authenticated read-only workspace at `GET /data.json`. It accepts only `GET` for the fixed page and asset routes. Files from a selected run directory are never served directly.

| Field | Source and meaning |
| --- | --- |
| `contract_version` | `pmi-r0-prototype/1` |
| `viewer` | The existing `pmi-ifc4d-viewer/1` document produced by the verified Stage 5.4C exporter. For live runs it must match the submitted viewer artifact byte for byte. |
| `viewer.model` | Model version and SHA-256 of the regenerated IFC. The existing relative URI identifies the bundle artifact on disk. The browser consumes verified tessellation via `elements`. |
| `elements[GlobalId]` | IFC name and class, world-coordinate XYZ vertices in metres, and zero-based triangular face indices from IfcOpenShell. Geometry is keyed by the original IFC GlobalId. |
| `viewer.activities_by_id[activityId]` | Label, kind, package ID, IFC task GlobalId, element GlobalIds, CPM timing and critical flag, CP-SAT timing and segments, and activity approval state. |
| `viewer.activity_ids_by_element_global_id[GlobalId]` | Seven original activity IDs per source element. |
| `viewer.packages` and `viewer.dependencies` | Three original work packages and 28 directed finish-to-start dependencies. Package membership and edge endpoints use schedule activity IDs. |
| `viewer.status` and `viewer.restriction` | Model and schedule digests, controlled schedule and approval status, and restriction text. |
| `proof` | Authenticated `schedule.json` proof projection containing solver status, project makespan, lower bound and scope. Runtime durations and interpreter metadata are omitted. |
| `origin` | Server-selected display label for the registered replay or authenticated application directory. |

For live bundles the required paths are `schedule.json`, `pipeline_evidence.json`, `ifc4d/scheduled.ifc`, `ifc4d/viewer.json`, and `ifc4d/round_trip.json`. The schedule digest is checked against pipeline evidence and the schedule content against the Stage 5.4C register. The verifier also compares the submitted IFC4D files with the regenerated output. Replay mode reads the registered accepted schedule at the selected resolution and generates its IFC4D bundle in temporary storage.

Schedule strings retain their source UTC offsets. The browser plots instants and labels them in Europe/Madrid time. The simulated playhead uses optimized intervals in either Gantt mode. Active means the playhead is inside an accepted optimized segment, with an exclusive finish. Completed means the optimized finish has been reached. These are presentation states derived from accepted timestamps.
