# Stage 5.4B.2 advanced construction constraints

Stage 5.4B.2 extends the fixed-duration CP-SAT scheduler and its timestamp validator. All 30 small references passed their applicable acceptance criteria, including the 22 original cases, RC06-D, five inspection cases and two strength cases. Both frozen R0 runs remain optimal at 14,850 and 14,880 elapsed minutes, with the original exclusions, full crew occupancy and EUR 1,172.5136 cost.

| Construction fixture | Unchanged input | Diagnostic coverage sensitivity |
| --- | --- | --- |
| Original | CP-SAT **INFEASIBLE** | CP-SAT **OPTIMAL**, 40,445 min, lower bound 40,445 |
| 1 March holiday | CP-SAT **INFEASIBLE** | CP-SAT **OPTIMAL**, 41,885 min, lower bound 41,885 |

The four column reservations open at FORM start and list REBAR among their covered activities. The cage-first dependencies put REBAR finish at or before FORM start. A positive-duration REBAR activity cannot satisfy both constraints. The published demonstration checker computes FORM-to-STRIP occupancy without checking this coverage. The diagnostic runs exclude only the earlier cage work from column formwork coverage in memory, retain all capacities and dependencies, and pass the timestamp validator. The unchanged fixtures require a coverage decision from the reference owner before benchmark acceptance. The calendar/precedence-only comparison reproduced 16,310 minutes and 29 conflicts across 11 pools in both fixtures.

## Model and validation

- **Reusable equipment** occupies one continuous interval per reservation. The interval ends after the latest release event plus the explicit return lead. The model and validator both check covered work. Unsupported reshoring configurations are rejected.
- **Concrete supply** uses exact rational scaling into integer rate pools. Daily limits integrate the declared rate over scheduled delivery ticks in each project-local day. For an authorized split pour, these ticks include restart overhead as a conservative planning allowance. Selected-mode productive durations and costs are carried through.
- **Events** can gate subsequent activities at an inspection finish or a recorded pass. Failed releases block descendants. Missing and planned evidence gives a conditional projection. The output distinguishes the controlled schedule status from CP-SAT’s proof status and its scope.
- **Authorized splits** use ordered optional intervals with a minimum length, fixed mode, restart time and declared gap policy. Without voluntary pauses, a segment that continues later fills the current intersection window and resumes in the next one. Retention holds crew and equipment across the gap. Split pours require separate cold-joint authorization.
- **Reference interpretation** follows R2 for RC13a. The embedded release row ends at the elapsed minimum, while the normative event semantics finish the release at the later recorded pass. The test checks the fixed pass and the published POUR and STRIP dates.
- **Scope** remains controlled. Normalized JSON declares supply as a `supply_source` resource with capacity in `m3/h` and per-activity draws in `resources`. Explicitly unsupported input structures are rejected. The acceptance matrix records benchmark failures and outstanding contract coverage.

## Reproduce from the repository root

```powershell
.\.venv-planning\Scripts\python.exe -B -m unittest -v research.implementation.stage5_4b.test_engine research.implementation.stage5_4b.test_advanced
.\.venv-planning\Scripts\python.exe -B -m research.implementation.stage5_4b --case RC06
.\.venv-planning\Scripts\python.exe -B -m research.implementation.stage5_4b --case RC12b
.\.venv-planning\Scripts\python.exe -B -m research.implementation.stage5_4b --frozen-r0 5
.\.venv-planning\Scripts\python.exe -B -m research.implementation.stage5_4b --frozen-r0 15
.\.venv-planning\Scripts\python.exe -B -m research.implementation.stage5_4b --demo original
.\.venv-planning\Scripts\python.exe -B -m research.implementation.stage5_4b --demo holiday
.\.venv-planning\Scripts\python.exe -B -m research.implementation.stage5_4b --demo original --coverage-sensitivity
.\.venv-planning\Scripts\python.exe -B -m research.implementation.stage5_4b --demo holiday --coverage-sensitivity
```

The CLI also accepts `--input PATH` for normalized controlled JSON. Exit code 0 indicates a validated OPTIMAL or FEASIBLE schedule. Exit code 1 covers conditional, blocked, invalid, infeasible or unverified outcomes. The [benchmark results](benchmark_results.json) record the measured solver statuses and bounds. The [acceptance matrix](acceptance_matrix.csv) records criterion-level evidence. Full Stage 5.4B acceptance remains pending.

Stage 5.4B.2 started at `d8a8ccb04fffdc7d21b1847f87750760ea0f1990`. All 88 pending approvals, Agent 2 references and the frozen outputs were preserved.

