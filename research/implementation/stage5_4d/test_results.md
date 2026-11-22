# Stage 5.4D verification

| Check | Result |
| --- | --- |
| Replays and application bundles | Both resolutions passed. Authenticated makespan and bound matched at 14,850 and 14,880 minutes. |
| Unsupported content | Missing application evidence, a substituted IFC with an updated viewer SHA, modified viewer content, a schedule forgery carrying its recomputed SHA, and C01 were rejected. |
| IFC and linkage | The three IFC GlobalIds and world-coordinate vertices and faces matched the source. All 21 activity links, seven per element, and all 28 dependency edges were present. |
| Edge browser interactions | WebGL model rendered. Orbit, zoom, pan, reset, direct 3D picking, keyboard Gantt selection, reverse highlighting, package filter and mode switch passed. CPM and CP-SAT bars had identical coordinates, with CPM critical outlines shown in CPM mode. |
| Animation and safety | Scrubbing, speed changes, play, pause and end-state counts passed. The notice and pending approval status were present. Both resolutions retained 88 pending approvals and eligibility false. |
| Regression | 43 historical Stage 5 tests, 6 IFC4D tests and 32 optimizer and integration tests passed. |

## Reproduce

Run the browser verifier from the repository root using the existing Playwright environment and Microsoft Edge. It builds fresh live runs in temporary directories, tests both forms of authenticated input, and captures screenshots after interaction. Use `--edge` to override the installed executable path.

```powershell
& .\.venv\Scripts\python.exe -B -m research.implementation.stage5_4d.verify_frontend `
  --screenshots research/implementation/stage5_4d/screenshots
& .\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_stage5_*.py'
& .\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_ifc4d_r0.py'
& .\.venv-planning\Scripts\python.exe -B -m unittest `
  research.implementation.stage5_4b.test_engine `
  research.implementation.stage5_4b.test_advanced `
  research.implementation.stage5_4b.test_review `
  research.implementation.stage5_4b.test_closure `
  research.implementation.stage5_4b_integration.test_integration
```

## Preservation evidence

The prototype writes its generated replay IFC and verification outputs to temporary directories. All Stage 5.4D source, docs and captures are in this directory. The accepted implementation, source IFC and scheduling artifacts match Stage 5.4C commit `1342ca6`. The following are raw checkout digests on the verified Windows workspace.

| Artifact | SHA-256 |
| --- | --- |
| `stage5_2/controlled_frame.ifc` | `8932ed0e043a1fb1252e51b223166c5c15b81f4969018a7e18c49e2802282c2c` |
| `stage5_4b_integration/r0_5_schedule.json` | `c892fe2756b943eb186bb7676ab0f3161b388e06c6df41b2a9ef9e850a22a9e0` |
| `stage5_4b_integration/r0_15_schedule.json` | `04ad9df154a7eed2aa431ebb1ce54931a0477cf079b06fe20c5e7a0759f5ca49` |
| `stage5_4c/scheduled.ifc` | `c50a585e4b88fedeea1ef11d6af67d504bcda24f63d33779c891c05c22d487b1` |
| `stage5_4c/viewer.json` | `7714a97804333d26e962d39d26448418437e00c521b496c3d4b7f5d1d8b7c93d` |
| `stage5_4c/round_trip.json` | `dff6b2138c09ef92d7373f019a388212a6f979d7f171ba15cac5502e9af88fc4` |

```powershell
git diff --exit-code 1342ca6 -- pmi_core research/planning `
  research/implementation/stage5_2 research/implementation/stage5_3 `
  research/implementation/stage5_4a research/implementation/stage5_4b `
  research/implementation/stage5_4b_integration/r0_5_schedule.json `
  research/implementation/stage5_4b_integration/r0_15_schedule.json `
  research/implementation/stage5_4c research/validation/engineering_approval_review
```
