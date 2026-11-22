# Stage 5.4C independent IFC4D verification

## Decision

**CONDITIONAL PASS.** The controlled R0 IFC4D export is correct for every bundle produced by the production application (`pmi_core.application --ifc4d`).

**A controlled frontend prototype may proceed**, using only bundles generated through the application path, for:
1. a 3D IFC viewer;
2. a linked interactive Gantt chart;
3. activity and element highlighting;
4. a CPM versus CP-SAT comparison;
5. animation using the optimized dates.

Two conditions apply (below). Real-project scheduling and expansion to other IFC models remain **not authorized**. All 88 approvals are PENDING and `real_project_eligible` is false.

### Conditions

| ID | Condition | Why |
| --- | --- | --- |
| **C1** | Before any bundle **not** produced in the same application run is consumed, for example through the standalone `python -m pmi_core.adapters.ifc4d --schedule <file>` replay path, the exporter must bind the schedule to its provenance or re-verify it. At minimum: check that `project_makespan_minutes` equals the latest optimized finish minus the project start and the lower bound; check the optimized durations against the accepted working and elapsed minutes; and verify the schedule SHA-256 against the application's pipeline evidence or a registered accepted artifact. | A forged schedule was **accepted**. I shifted the final activity a day later, kept it after its predecessors, and left the proven makespan of 14,850 min unchanged. The exporter wrote a "CP-SAT" IFC4D bundle whose task dates contradict the recorded proof. The structural gates check identity, counts, approvals and predecessor order, but not consistency with the optimizer result. |
| **C2** | Commit Stage 5.4C. This acceptance applies to the exact working-tree files below, and must be re-confirmed by hash at the commit. | Stage 5.4C is **uncommitted**: HEAD is `ee9676a`, `application.py` is modified, and the adapter, viewer builder and tests are untracked. |

## Baseline

**Repository**
- HEAD is `ee9676ad122fe8d8dc53efde41cbcb45baf9128f`.
- In the working tree, `pmi_core/application.py` is modified. These are untracked:
  - `pmi_core/adapters/ifc4d.py`;
  - `pmi_core/viewer_data.py`;
  - `tests/test_ifc4d_r0.py`;
  - `research/implementation/stage5_4c/`;
  - Agent 1's documentation CSVs in `stage5_4b_integration/resource_handover/`;
  - this folder and my earlier `reconfirmation_ee9676a.md`.

**Verified implementation (SHA-256, unchanged from start to end of the run)**
- `application.py`: `6495bdfa2ae5adb3…`
- `adapters/ifc4d.py`: `6c0775f9604c4c7c…`
- `viewer_data.py`: `a69fafaf995384b6…`
- `tests/test_ifc4d_r0.py`: `adbe781718c1c678…`

**Change since `ee9676a`.** The only tracked change is a 6-line `--ifc4d` hook that calls the adapter in the IFC interpreter after the schedule is published. There is **no** tracked difference in any of these:
- `pmi_core/optimization`, `scheduling`, `estimation`, `construction` and `schedule_result.py`;
- `research/implementation/stage5_2`, `5_3`, `5_4a`, `5_4b` and `5_4b_integration`;
- `research/validation/`, including approval materials and independent evidence;
- `tests/test_stage5_*.py`.

## Commands executed

All commands ran from the repository root.

~~~powershell
.\.venv\Scripts\python.exe -B research/validation/stage5_4c_independent/scripts/verify_5_4c.py
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_ifc4d_r0.py'
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_stage5_*.py'
.\.venv-planning\Scripts\python.exe -B -m unittest research.implementation.stage5_4b.test_engine research.implementation.stage5_4b.test_advanced research.implementation.stage5_4b.test_review research.implementation.stage5_4b.test_closure research.implementation.stage5_4b_integration.test_integration
.\.venv-planning\Scripts\python.exe -B -m pmi_core.scheduling --config research/implementation/stage5_4a/controlled_schedule_inputs.json --output <temp>
~~~

`verify_5_4c.py` runs `pmi_core.application --ifc4d` at ticks 5 and 15 into temporary directories. EXPRESS rules were attempted with `ifcopenshell.validate(..., express_rules=True)` on temporary copies.

Results are in [independent_ifc4d_results.json](independent_ifc4d_results.json).

## Independent checks and results

The exporter's own round-trip checker was **not** relied on. Source preservation was checked by raw STEP text comparison, without IfcOpenShell. Semantics were re-read by my code. Schedules were reconciled against the accepted 5.4B.3 artifacts and my independent Stage 5.4A model.

| Area | 5-min | 15-min |
| --- | --- | --- |
| Application exit / status / scope | 0 / OPTIMAL / complete project | 0 / OPTIMAL / complete project |
| Makespan = lower bound | **14,850** | **14,880** |
| Independent Stage 5.4A model on the produced schedule | 0 errors; makespan 14,850 | 0 errors; makespan 14,880 |
| Produced `schedule.json` vs accepted 5.4B.3 artifact (runtimes and evidence excluded) | identical | identical |
| Direct reference cost | €1,172.5136 | €1,172.5136 |
| Source elements / packages / activities / assignments / sequences | 3 / 3 / 21 / 21 / 28 | 3 / 3 / 21 / 21 / 28 |
| Source STEP instances byte-identical (raw text) | 73/73 | 73/73 |
| Added instances | 282 schedule and provenance entities only; no elements, representations, placements, points, units or quantities | same |
| World-coordinate geometry, SI units, 6 authored quantities | identical to the source | identical to the source |
| Element GlobalIds | `24tlOXIsvMQfyRLiqh6fZt`, `1jDfy2_jTRueAw6f5fc3Ev`, `3wOB$MtWLSz8SJNgW3VJvy` | same |

The added instances break down as:
- 1 work plan and 1 work schedule;
- 24 tasks and 21 task times;
- 3 nesting, 1 control-assignment, 21 process-assignment and 28 sequence relationships;
- 1 declaration and 1 aggregation;
- 22 property sets with 136 values.

Task GlobalIds are identical across both resolutions.

### IFC4D semantics

| Entity | Finding |
| --- | --- |
| `IfcWorkPlan` / `IfcWorkSchedule` | The project declares the plan (`IfcRelDeclares`), and the plan aggregates the schedule (`IfcRelAggregates`). Both are PLANNED. The schedule's StartTime and FinishTime equal the earliest optimized start and the latest optimized finish. The use restriction is in the Description. |
| `IfcTask` hierarchy | The schedule controls the 3 package summary tasks (`IfcRelAssignsToControl`). Each package nests its 7 activity tasks (`IfcRelNests`) in the schedule's order. Identification is the PMI activity or package ID. |
| `IfcTaskTime` | One per activity, with `DataOrigin = PREDICTED` and no actual dates. ScheduleStart and ScheduleFinish equal the CP-SAT dates exactly, with `+01:00` offsets (Europe/Madrid in January). There is no ScheduleDuration (optional). |
| `IfcRelSequence` | 28 relationships equal to the accepted dependencies and correctly directed (predecessor as RelatingProcess). All are `FINISH_START` with `TimeLag` absent, which represents zero lag. Every predecessor finishes before its successor starts. |
| `IfcRelAssignsToProcess` | 21 relationships, one per activity, each to the activity's source element: 7 per element. |
| Validation | IfcOpenShell structural schema validation passes, as in the exporter. **EXPRESS rule execution was not achieved.** `validate(express_rules=True)` exists, but it needs `pytest` (`_pytest`), which is not installed. Installing it was outside this task. It can be run safely in a separate, isolated environment. Structural validation is **not** a substitute for complete semantic validation (L1). |

### Viewer contract (`viewer.json`, `pmi-ifc4d-viewer/1`)

These checks passed at both resolutions:
- `model.uri` resolves to the exported `scheduled.ifc`, and `model.sha256` matches it;
- all 21 activities reference valid source GlobalIds;
- the reverse element-to-activity index is complete (7 per element);
- each activity's `ifc_task_global_id` matches the IFC;
- CPM (`cpm`, with `cpm_critical`) and CP-SAT (`cp_sat`, with `segments`) are separate fields;
- the 28 dependencies are complete and directed;
- the PENDING status, 88 pending approvals, eligibility false, the restriction label and per-activity approval IDs are all visible.

**Sufficiency for a 3D viewer with a linked Gantt chart:** sufficient for selection linking, highlighting, Gantt bars, dependency arrows and animation. Gaps are listed as L4 and L5.

### Negative tests

All run through the exporter CLI or the application.

| Test | Result |
| --- | --- |
| C01 v1.1 schedule, which has no IFC identity | Rejected; no output, no fabricated geometry |
| Altered IFC bytes / a different IFC as source | Rejected by the R0 hash gate |
| Approval set to APPROVED / one approval removed / `real_project_eligible` true / conditional scope | Rejected |
| Dependency removed / duplicated / reversed / unknown endpoint / nonzero lag | Rejected |
| Activity mapped to an unknown element | Rejected |
| Existing output directory (exporter and application) | Rejected; previous bundle byte-identical; no staging leftovers |
| **Forged, internally consistent date shift** | **Accepted and exported (C1)** |

### Regression and preservation

- **Tests:** 3/3 focused IFC4D, 43/43 historical, and 32/32 optimizer and integration tests pass.
- **Frozen exports:** 8/8 Stage 5.4A exports are byte-identical.
- **Manifests:** the Task 7 (66 files), C01 (15), Stage 5.4B.2 final (9) and integration-prep manifests are all unchanged.
- **Approvals:** the register is unchanged (`d86a26ce…`), and all 88 approvals are PENDING.

## Findings

**Blockers:** none for the controlled frontend prototype when it uses application-produced bundles. C1 blocks the replay and standalone path. C2 is procedural.

**Nonblocking limitations**

- **L1:** EXPRESS rules were not executed, because `pytest` is missing. Run them in an isolated environment before external exchange.
- **L2:** every activity, including curing and strength-release holds and inspections, is `IfcTask.PredefinedType = CONSTRUCTION`. The hold and inspection semantics survive only in `viewer.json` and the provenance psets. Consider `USERDEFINED` with an ObjectType of CURING_HOLD, STRENGTH_RELEASE or INSPECTION.
- **L3:** the IfcDateTime values carry ISO 8601 UTC offsets. How external viewers interpret them is unverified, so the frontend should use the offset-aware `viewer.json` times.
- **L4:** for R0, the CPM and CP-SAT dates are identical, because the CPM schedule is already resource-feasible. The comparison view will show no difference on this fixture.
- **L5:** `viewer.json` has no project proof (makespan and bound), no CPM critical-path edges (per-activity flags only), no working calendar for non-working shading, and no resource occupancy. These exist in `schedule.json`, which is referenced only by digest and not by URI.
- **L6 (I04):**
  - The adapter hard-codes the R0 hash, model ID, project ID and the counts 3, 7, 21 and 28.
  - The scheduling worker remains a research fixture adapter.
  - This is correct and not blocking for a **controlled R0** visualization. It **is** a blocker for any other IFC model or uncontrolled input.
- **L7:** optimized segments appear only in `viewer.json`, not in IFC. R0 has single-segment activities, so nothing is lost here.

**Future improvements**

- Implement C1 as a schedule-authenticity and consistency gate.
- Add EXPRESS rules to an isolated CI environment.
- Add explicit IfcTask types for holds and inspections.
- Add a `schedule_uri`, proof, critical edges and calendar to the viewer contract.
- Test with an external web IFC loader.
- Develop a production scheduling worker before any non-R0 model.

No production code, fixtures, approvals or input eligibility were changed, and Stage 5.5 was not started. Nothing was committed or pushed.
