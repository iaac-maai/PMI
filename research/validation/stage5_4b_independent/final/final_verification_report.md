# Stage 5.4B.2 final independent verification

## Decision

**CONDITIONAL PASS.**

All **84 of 84 mandatory criteria** are independently accepted, and the matrix has 86 criteria in total ([final_acceptance_matrix.csv](final_acceptance_matrix.csv)). **AC-G03 is closed** on independent evidence.

There is one condition (F01). The split-pour supply report gives the conservative restart allowance as exact draw: 63 m³ reported against 60 m³ placed. This does not affect any schedule, benchmark or mandatory criterion. It must be corrected before supply reports are exposed through integration.

**Stage 5.4B.3 architectural integration: may proceed**, provided F01 is fixed before supply-report outputs are consumed. Real-project scheduling remains prohibited: all 88 approvals are PENDING and `real_project_eligible` is false everywhere.

## Baseline and stability

- The reviewed commit is `cf8f4581e65e027cd843ed42c81384a5d60224ef`.
- HEAD and the SHA-256 of every file under `research/implementation/stage5_4b/` were identical at the start and end of the run.
- The only working-tree change during verification is this folder.
- Runs used OR-Tools 9.15.6755 in `.venv-planning` with `PYTHONHASHSEED=0`.
- Agent 1's PASS labels were not used as evidence.

## Oracles

Agent 1's solver was exercised through its public API and the normal `--demo` CLI path, without coverage sensitivity. Every output was then checked by code that shares nothing with it:

1. **Expected outcomes:**
   - my Task 4 exhaustive engine, re-run under the R2 default calendar policy, with RC06 under its registered exception;
   - the Task 7 and C01 reference values;
   - for date-capacity scenarios, the same engine with dated capacities applied independently of `capacity_periods()`.
2. **A per-minute timestamp checker** ([scripts/verify_final.py](scripts/verify_final.py)) that reads the **original source-case JSON**. It covers:
   - durations, split segment counts and minimum lengths, and no voluntary pause;
   - project, resource, exception and `allowed_hours` calendars;
   - FS lags and inspection gates;
   - recorded-pass bounds and strength-release timing measured from the pour;
   - per-minute capacity, including continuous reservations and dated capacities;
   - deadlines and the reported objective.
3. **The C01 coverage-aware checker** on the hash-verified v1.1 source JSON, which runs 350 checks per fixture.
4. **The independent Stage 5.4A model** for the frozen R0 handovers.

## Results

| Area | Independent result |
| --- | --- |
| **AC-G03**: timestamps of all 30 small cases | **30/30 PASS** ([independent_case_results.csv](independent_case_results.csv)). |
| Advanced reservations, splits and supply | RC05a/b reservations match the exhaustive optima. RC10a/c splits match the reference dates, with no voluntary pause. RC11a/b supply matches the reference dates. |
| Inspection and strength events | RC12a–e give OPTIMAL, CONDITIONAL (P conditional), BLOCKED (P blocked; scope `unblocked_subset`), recorded pass at 265 min, and EVENT_BEFORE_ACTIVITY_FINISH. RC13a releases at max(minimum, recorded) = 15 Jan 10:30. RC13b is CONDITIONAL at 5,880 min, with RELEASE and STRIP conditional. |
| Optimal results | All have bound = objective, a gap of 0 and solver status OPTIMAL. Conditional and blocked outcomes carry their own status and scope. |
| Corrected benchmarks, v1.1 | Original: **OPTIMAL 40,445 min**, completing 2027-03-01 10:05. Holiday: **OPTIMAL 41,885 min**, completing 2027-03-02 10:05. Both have bound = objective and zero conflicts, pass **350/350** checks (108 coverage), and have 70 activities, 98 dependencies, 16 reservations and €5,103.32664. CPM: 16,310 min, 29 conflicts on 11 pools. Hashes match the C01 manifest, coverage sensitivity is off and the CLI exits with 0 ([independent_benchmark_results.csv](independent_benchmark_results.csv)). |
| Historical negatives, v1.0 | Both are INFEASIBLE before solving: `STRUCTURAL_INFEASIBILITY / RESERVATION_COVERAGE_PREDECESSOR` (R-COLSET-C1, C1-REBAR → C1-FORM), with no schedule, no solver status, exit code 1 and unchanged hashes. The diagnostic names one of the four contradictions (F02). |
| Frozen R0 | 14,850 and 14,880 min OPTIMAL, with no independent errors and €1,172.5136. C-POUR keeps the full HYP-CONC crew including OFICIAL_1, and both runs carry 88 PENDING approvals. |
| CD01–CD09 | All confirmed: explicit-none demand gives MISSING_INPUT; mode fields without a crew mode give MODE_MISMATCH; injected APPROVED rows and unregistered fixture exceptions are rejected; HORIZON_EXHAUSTED comes with a validated extended-horizon witness; ignored exceptions are reported; R0 explicit-none equipment is declared and its removal is rejected; bounds are integers; `timestamp_source` is reported. CD07 is documented (F05). |
| Input-state audit | All 12 probes behave as specified. `engineer_approved` is rejected on resources, activities, calendars and reservation releases. Unregistered states and absent states or evidence fields are rejected. `user_provided_project` and `independently_measured` require an evidence reference, which is preserved in the output. A hypothetical pass with a missing state is rejected. |
| Contract diagnostics | V4, V6, V7, V8 successor contradiction, reservation quantity, reshoring, misclassified reservation, unauthorized and cold-joint splits, missing supply rate, NO_ELIGIBLE_MODE detail, TICK_MISALIGNED and real-project scope all return the specified codes. |
| Date-specific capacity | Six scenarios equal my independent enumeration (below). |
| Invalid capacity overrides | Non-ISO keys, negative or fractional values, missing units, non-object maps, explicit none acquiring capacity, and duplicate JSON keys via the CLI are all rejected. An explicit-none zero override is accepted. |
| Override timezones and validation | A London-calendar resource changes at London midnight. A continuous asset changes at Madrid midnight, including the 1,380-minute DST day. The production validator and my checker both reject a schedule placed on a zero-capacity day. |
| Regression and preservation | **43/43** historical tests and **27/27** optimizer tests pass. **8/8** Stage 5.4A exports are byte-identical. The approval register is unchanged (`d86a26ce…`), with 88 PENDING. The Task 7 manifest (66 files) and C01 manifest (15 files) are unchanged, and the v1.0 hashes are intact. |

The six date-capacity scenarios:

| Scenario | Makespan (min) |
| --- | ---: |
| Crew reduced to zero | 3,050 |
| Crew increased 1→2 | 370 |
| Crane outage | 1,650 |
| Continuous formwork reservation crossing a zero-capacity day | 6,000 |
| Supply rate 6→12 m³/h | 330 |
| Supply rate 6→3 m³/h | 1,575 |

## Specific reviews requested

- **Secondary earlier-start objective.** It runs only after a proven primary optimum, with the makespan fixed. It is skipped for problems with 40 or more activities, so both benchmarks report `timestamp_source: primary`. Status, objective and bound always come from the primary solve.
- **Unsupported constraints through normalized JSON.** Unknown keys and unsupported constructs are rejected before solving, including through `--input`.
- **Resource-local versus project-local dates for continuous assets.** **Accepted**, with the narrow clarification in F07. Dates are in the resource calendar's timezone, or the project timezone for continuous assets. Each date runs from local midnight to local midnight, including DST days.
- **Split-pour restart supply allowance.** The *model* treats restart minutes as supply draw and counts them against daily limits. That is a conservative planning choice, documented in Agent 1's report. The *output* presents the result as `draw_m3_exact`: 63 m³ against 60 m³ placed. This is the misrepresentation recorded as condition F01.

## Discrepancies

See [discrepancy_register.csv](discrepancy_register.csv):

- **F01:** condition. Separate the restart allowance from placed volume.
- **F02:** list every structural contradiction in the diagnostic.
- **F03:** a BLOCKED objective is the unblocked subset's makespan, not the project's.
- **F04:** benchmark dates may vary with multi-worker solving. This is expected, and dates are excluded from acceptance.
- **F05:** the internal validator shares preparation code with the model.
- **F06:** RC13b in my reference package lacks `acceptance_criterion_ref`.
- **F07:** the date-capacity timezone clarification.

## Conditions to close

1. **F01:** report `placed_volume_m3` and `restart_allowance_m3` separately, or rename the field to an allowance. Label restart occupancy accordingly, and add a narrow contract note that rate pools and daily limits count the restart allowance conservatively.

Recommended, not conditions: F02, F03, F06 and F07.

## Reproduce

~~~powershell
$env:PYTHONHASHSEED = "0"
& .\.venv-planning\Scripts\python.exe -B 'research/validation/stage5_4b_independent/final/scripts/verify_final.py'
& .\.venv-planning\Scripts\python.exe -B 'research/validation/stage5_4b_independent/final/scripts/build_final_matrix.py'
~~~

The first command takes about 30 s. It writes the case and benchmark CSVs and `verification_evidence.json`, and reruns both test suites and the Stage 5.4A exports. The second writes `final_acceptance_matrix.csv` and `matrix_summary.json`.

No production code was modified. Nothing was approved, installed, trained, committed or pushed.
