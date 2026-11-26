# PMI Speckle milestone initial implementation

The separate controlled run processes the synthetic candidate IFC4 through strict IFC ingestion, Stage 5.2 construction, engineering estimation, CPM, CP-SAT and IFC4D. It has passed local regression and browser checks. Agent 2's independent model qualification and live Speckle linking are pending.

## Files and environment

- `application.py` snapshots the hash-registered IFC and hypothetical manifest, runs the IFC and planning interpreters, binds the outputs to SHA-256 provenance and publishes a fresh bundle only after re-import verification.
- `engineering.py` qualifies and measures the IFC, consumes the actual Stage 5.2 output, and reuses the BCCA engineering estimate routine. `worker.py` consumes the derived handover through the existing CPM and CP-SAT engines. `speckle_frame.ifc`, `manifest.json` and `.gitattributes` define the local candidate and preserve the registered bytes.
- `ifc4d.py` adds the tasks, assignments and dependencies. `fallback.py` exposes a fresh-run-only local viewer using the accepted Stage 5.4D browser assets. `test_milestone.py` covers repeated fresh runs and Edge.
- `speckle_identity.py` retrieves a pinned IFC upload bundle and reads explicit IFC GUID properties. `requirements-speckle-lock.txt` records resolved SDK packages. The repository ignore rule excludes `.venv-speckle/`.

The separate SDK environment is `C:\Users\Chloe\PMI\PMI\.venv-speckle\Scripts\python.exe`, CPython 3.14.7 Windows AMD64, with SpecklePy 2026.9.0b3 and PyArrow 26.0.1. No packages were installed into either accepted environment. The SDK signature check confirmed `receive3` and supports disabling receipt marking.

## Reproduce locally

From the repository root, choose a fresh output directory with an existing parent.

```powershell
& .\.venv-planning\Scripts\python.exe -B -m research.implementation.speckle_milestone.application --output outputs/speckle-review
& .\.venv\Scripts\python.exe -B -m research.implementation.speckle_milestone.fallback
& .\.venv\Scripts\python.exe -B -m unittest research.implementation.speckle_milestone.test_milestone
```

The fallback serves the fresh bundle on `http://127.0.0.1:8771`. It ignores submitted bundle paths and creates a new registered run. Edge verified both directions of selection, mode switching, and the final playback state.

After the lead confirms the exact candidate and access settings, upload the unchanged `speckle_frame.ifc` through the designated project. Its SHA-256 is `d06a3a78649e0e401be7faeaf148321a317dcfb8aa11ba13211a38fc2680b467`. Set `PMI_SPECKLE_TOKEN` via the local secret mechanism, then run the read-only inspection below with the project, model and pinned version identifiers.

```powershell
& .\.venv-speckle\Scripts\python.exe -B -m research.implementation.speckle_milestone.speckle_identity `
  --project <project-id> --model <model-id> --version <version-id> `
  --ifc-identities outputs/speckle-review/ifc_identities.json
```

The inspector supports the configured Speckle Cloud host and the reviewed IFC bundle format. It rejects missing, duplicate or conflicting GUID links. The test uses distinct explicit IFC and Speckle application IDs. A live `viewer_object_id` remains unset pending a selection/filter proof against the actual hosted version. The upload and live receive have not been run.

## Independent verification handoff

- Qualify the candidate independently. Expected represented concrete quantities are 0.544, 0.800 and 2.400 m³. Recompute the declared durations, crew constraints and two support edges from `manifest.json`. Input formwork and rebar quantities are explicit hypothetical declarations. The test frame excludes unsupported construction methods and real release evidence.
- Reproduce the three packages, 21 activities, 26 edges and 20,295-minute CPM and CP-SAT makespans. Equal makespans can coexist with different activity dates. Check the optimum bound and timestamps independently.
- Re-import `scheduled.ifc` independently. Verify all 73 original instances, original GlobalIds, assignments, nesting, dependencies and planned timestamps. The artifact passed structural schema validation. Full EXPRESS rules were outside this run.
- Once access is available, verify all three original IFC GUIDs in the Speckle response and match each one to a viewer-selectable node. Demonstrate activity-to-element and element-to-activity selection on the pinned version before wiring the hosted viewer. The local linked view is ready as fallback.
- Reviewed preservation status covers the accepted R0 code and artifacts. Historical tests passed 43/43, R0 IFC4D 6/6, optimizer/integration 32/32, and new milestone tests 2/2. All 88 approvals are pending, AP-TOL is unset, and real-project eligibility is false.
