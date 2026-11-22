# Stage 5.4C IFC4D implementation report

Stage 5.4B.3 independently accepted the pipeline and authorized controlled IFC4D development. This implementation covers the registered R0 IFC4 model at the accepted 5- and 15-minute resolutions. The example bundle uses the committed 5-minute schedule. All 88 engineering approvals are pending and construction use is prohibited.

## Architecture

The application already creates a unified `pmi-schedule/1` JSON artifact after IFC ingestion, work-package generation, estimation, CPM and CP-SAT. The optional `--ifc4d` switch passes the source IFC and that artifact to the IFC runtime after scheduling. The optimizer and CPM engine continue to produce all dates. The application still uses separate IFC and planning interpreters.

The Stage 3.3b and Stage 3.8b research exporters establish the IFC pattern of creating schedule and sequence entities and assigning task times directly. Their input formats, date conversions and derivation logic are specific to older experiments. The new adapter reuses the already installed IfcOpenShell library and applies that entity pattern directly to the accepted application contract. R0 is IFC4, so there is no schema migration. The adapter opens the original geometry and adds schedule entities in memory, validates a staged export, then publishes the bundle to a new directory.

Each activity has a planned, predicted `IfcTaskTime` containing the offset-aware CP-SAT start and finish. Package summary tasks preserve the original package IDs and ordered activity membership. An `IfcRelAssignsToProcess` links each activity to the source element it operates on. A finish-to-start `IfcRelSequence` carries each R0 dependency. Its description preserves the PMI rule, origin, condition and zero elapsed lag. Package and activity IFC GlobalIds are deterministic across resolutions. The field mapping records where provenance and use restrictions are stored.

Standalone replay authenticates the registered accepted schedule bytes. The live application binds its schedule to the IFC export through the pipeline evidence and verifies stable schedule content against the registered R0 results. The [closure report](closure_report.md) documents both gates and the independent recheck.

## Viewer interface

`viewer.json` implements `pmi-ifc4d-viewer/1`. Load `model.uri` relative to the JSON file and use `model.sha256` to bind it to the verified IFC. Gantt rows come from `activities_by_id`. The `cpm` and `cp_sat` fields carry their respective times and timing details. CPM criticality stays with CPM. The optimized segments remain available for rendering breaks within activity intervals.

Use `activities_by_id[id].element_global_ids` to highlight an IFC element from an activity selection, and `activity_ids_by_element_global_id[globalId]` for the reverse selection. Draw dependency arrows by matching the predecessor and successor activity IDs. Display the supplied schedule restriction and the activity input and approval states. For R0 the CPM and optimized timestamps coincide within each resolution. Frontend work is outside this stage.

## Verification and reproduction

The example IFC was reopened in IfcOpenShell. All 73 original STEP instances matched, including model identities, placements, units and geometry. The re-import recovered three packages, 21 timed activities, 21 element assignments and 28 dependency edges. The IFC passed structural schema validation and the exporter checked the recovered relationships and fields against the schedule. The focused tests also independently tessellated the source and both re-imported outputs in world coordinates and compared vertices and faces.

IFC4 structural checks and PMI round-trip checks were run in the installed IFC runtime. Optional IfcOpenShell EXPRESS rule execution requires an additional test dependency absent from that runtime. External viewer compatibility is unverified.

To replay the example in a new directory run the following command from the repository root.

```powershell
& .\.venv\Scripts\python.exe -B -m pmi_core.adapters.ifc4d `
  --source research/implementation/stage5_2/controlled_frame.ifc `
  --schedule research/implementation/stage5_4b_integration/r0_5_schedule.json `
  --output r0-ifc4d-replay
```

The output directory's parent must already exist. For a live run add `--ifc4d` to the accepted `pmi_core.application` command. The bundle appears under `<output>/ifc4d` beside the normal pipeline artifacts. The C01 benchmark is rejected by the IFC-backed R0 gate and does not produce an IFC.

- [Independent Stage 5.4B.3 acceptance](../../validation/stage5_4b_independent/integration_final/integration_acceptance_report.md)
- [Field mapping](field_mapping.csv)
- [Controlled IFC4D example](scheduled.ifc)
- [Round-trip evidence](round_trip.json)
- [Viewer contract example](viewer.json)
- [Test results](test_results.md)

Stage 5.4C is ready for independent verification within the R0 scope.
