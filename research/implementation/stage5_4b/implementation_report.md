# Stage 5.4B.2 implementation closure

The optimizer ran both C01 v1.1 fixtures directly from the hash-verified paths in Agent 2's correction manifest. Both schedules passed the internal timestamp validator and all 350 checks per fixture in Agent 2's separate C01 checker, including 108 reservation coverage checks each. The exported schedules include all 70 activities, 16 continuous reservations, resource occupancy, capacity and supply checks, and solver statistics.

| Fixture | Status | Objective and lower bound | Gap | Resource conflicts |
| --- | --- | ---: | ---: | ---: |
| Original v1.1 | OPTIMAL | 40,445 min | 0 | 0 |
| Holiday v1.1 | OPTIMAL | 41,885 min | 0 | 0 |
| Original and holiday v1.0 | INFEASIBLE in static validation | | | |

The original finishes 1 March 2027 at 10:05 and the holiday variant finishes 2 March at 10:05, both in Europe/Madrid. Direct reference cost stays EUR 5,103.32664, or EUR 5,103.33 rounded to cents. The CPM comparison remains 16,310 minutes with 29 conflicts across 11 pools. In both v1.0 files, a column reservation opens after the cage work that it purports to cover. Those files remain negative regressions and yield a named contradiction before solver invocation.

## Input-state and override behavior

The validator uses the five registered values from Stage 5.3A and the R2 resource contract. Missing mandatory inputs stop the solve. Missing inspection or strength evidence can be retained as a conditional projection under R2. User-provided and independently measured inputs retain their state and evidence reference. Unverified engineer-approved inputs are rejected. Legacy fixture adapters record the provenance supplied by the controlled reference package. All 88 registered approvals remain pending, and real-project eligibility is false.

The date-capacity map replaces a resource's nominal capacity on the declared local date. Calendar availability still governs working segments, and physical reservations stay continuous. Each segment or reservation is checked across the full interval, including capacity changes inside the interval. The solver uses fixed capacity-deficit intervals and the internal timestamp validator checks the dated profile at occupancy and capacity boundaries. Date capacities use the existing resource unit. Integer overrides for concrete rates are scaled exactly alongside the nominal and drawn rates. An explicit-none resource cannot acquire capacity through an override.

The contract calls the override date local without specifying a separate timezone for continuous assets. The implementation uses the resource calendar's local date where a calendar is declared and the project calendar's timezone for continuous assets. This is the only timezone declared for those assets in the normalized inputs. Calendar windows, local midnight alignment and conflicting declarations are validated before solving. The existing same-day working-window syntax governs working segments across midnight. Tests cover split work and a continuous reservation across date boundaries.

## Verification and acceptance

The regression suites cover 43 historical tests and 27 optimizer tests, including all 30 small references, the two frozen R0 optima, the CD01-CD09 review, and the new provenance and capacity overrides. Both R0 exclusions and optimal results at 14,850 and 14,880 minutes are preserved.

The internal timestamp validator shares input normalization, calendar and capacity-profile construction with the optimizer. It checks returned timestamps, loads and release coverage without using solver variables. Agent 2's source-fixture checker remains the independent acceptance basis. The separate core checker also passed on all 17 applicable core references and both frozen handovers. Final independent review of all advanced small-case timestamps remains open under AC-G03. No remaining implementation blocker was identified.

C01 replaces six existing criteria and adds two mandatory criteria. The [current matrix](acceptance_matrix.csv) therefore has 86 criteria, 84 mandatory. The recorded dispositions are 84 passed, one deferred and one not applicable. The [pre-C01 matrix](acceptance_matrix_pre_C01.csv) preserves the earlier disposition. [Benchmark results](benchmark_results.json) link to the complete JSON exports.

## Reproduce from the repository root

```powershell
.\.venv-planning\Scripts\python.exe -B -m research.implementation.stage5_4b --demo original
.\.venv-planning\Scripts\python.exe -B -m research.implementation.stage5_4b --demo holiday
.\.venv-planning\Scripts\python.exe -B -m research.implementation.stage5_4b --demo original --benchmark-version v1.0
.\.venv-planning\Scripts\python.exe -B -m research.implementation.stage5_4b --demo holiday --benchmark-version v1.0
.\.venv-planning\Scripts\python.exe -B -m research.implementation.stage5_4b.export_benchmarks
.\.venv-planning\Scripts\python.exe -B -m unittest research.implementation.stage5_4b.test_engine research.implementation.stage5_4b.test_advanced research.implementation.stage5_4b.test_review research.implementation.stage5_4b.test_closure
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_stage5_*.py'
```

The CLI also accepts `--case`, `--frozen-r0`, and `--input PATH` for normalized controlled JSON. It returns exit code 0 for a validated OPTIMAL or FEASIBLE schedule and 1 for conditional, blocked, invalid, infeasible or unverified outcomes.

