# Stage 5.4B.1 independent verification: CP-SAT core

**Verdict: CONDITIONAL PASS.**

The core optimizer is correct for its declared scope:
- All 17 applicable reference outcomes and all 13 deferred rejections are confirmed by oracles that share none of its code.
- Both R0 optima and the cost are confirmed.
- The approvals are preserved.
- The secondary objective cannot change the reported status, objective or bound.
- No unsupported constraint is silently scheduled.

The condition: one of Agent 1's 41 PASSED acceptance claims (AC-C-V2) is only partially met, and eight further findings are nonblocking. See [discrepancy_register.csv](discrepancy_register.csv). None affects a verified outcome. They should be fixed or reclassified before Stage 5.4B.2 acceptance.

Scope: commit `d8a8ccb`, which holds the six reviewed `research/implementation/stage5_4b/` files. Run with OR-Tools 9.15.6755 in `.venv-planning`. An untracked `advanced.py` appeared in that folder during verification. It is outside this scope, was not reviewed and is not imported by the verified code; the six committed files are unchanged against `d8a8ccb`. No production code, dataset or approval was modified. Nothing was installed, committed or pushed.

## Oracles

The production solver is the system under test. Its `validate()` was **not** used as the oracle (CD07). The script is [scripts/verify_core.py](scripts/verify_core.py), and it uses three independent checks:

1. **Expected outcomes.** My Task 4 exhaustive engine, re-run under the R2 default calendar policy, with RC06 under its registered exception. It reuses the enumeration and brute-force proofs.
2. **A per-minute schedule checker.** It reads the **original reference-case JSON**, not Agent 1's normalized problem, and checks every returned timestamp against:
   - durations, grid and segments;
   - the project, resource and exception calendars, `allowed_hours` and `not_before`;
   - FS lags;
   - per-minute capacity;
   - deadlines;
   - the reported objective.
3. **For frozen R0, my independent Stage 5.4A model** (`independent_cpm.py`), using BCCA names and aliases. It covers the 28 edges, durations, Madrid calendar with holiday, pour window, strike anchoring, capacities, full-crew occupancy and cost.

## Results

| # | Item | Result |
| --- | --- | --- |
| 1 | 17 applicable cases | **17/17 PASS.** Statuses, makespans and diagnostics match. Each optimal case has bound = objective, gap 0 and solver status OPTIMAL. The per-minute check is clean, and unique schedules match exactly (RC02, RC06, RC06-D, RC07c). |
| 2 | 13 deferred cases | **13/13 PASS.** Each is MODEL_INVALID / UNSUPPORTED_CONSTRAINT before solving, with `solver_status` null and no activities. The message names the deferred feature: reservations, interruption, m³/h supply, inspection_pass_events or strength_events. |
| 3 | RC06 / RC06-D | RC06 starts N on Tuesday at 07:00 under CAL-EXC-RC06. RC06-D starts N at 08:00. Both are 4,520 min. An unauthorized exception falls back to the default policy (CD05). |
| 4 | R0, 5-minute tick | OPTIMAL **14,850 min**, completing 2027-01-14 15:30. Equals the independent CPM, with no independent errors. |
| 5 | R0, 15-minute tick | OPTIMAL **14,880 min**, completing 2027-01-14 16:00. Equals the independent CPM, with no independent errors. |
| 6 | Cost | **€1,172.5136** as the reported total, as the sum of the 12 activity lines and in the independent model, at both ticks |
| 7 | Crew occupancy | C-POUR occupies PEÓN ×2, OFICIAL ×1 and VIBRADOR ×1, the full HYP-CONC crew. The *oficial* is declared `reserved_without_bcca_demand` under AP-X-CREW-01, and all occupancies match the independent model. Removing the *oficial* gives MODE_MISMATCH, and inflating hours past units × scheduled time is rejected (V4). |
| 8 | Deadlines and status | The project-deadline core diagnostic works (RC07a INFEASIBLE / INFEASIBLE_DEADLINE). It identifies the implicated prerequisites, including a two-deadline core driven by capacity. A deadline that precedence alone makes impossible is rejected before solving. One gap: infeasibility without deadlines has no diagnostic (CD04). |
| 9 | Timestamp validation | Every returned schedule passes the independent checker. The production validator rejects a deliberately conflicting schedule (Agent 1's test), but it shares calendar construction with the model (CD07). |
| 10 | Acceptance matrix | Same 84 IDs. Of the 41 PASSED claims, **40 are confirmed** and **1 is partial**: AC-C-V2, explicit none demanded (CD01). AC-C-V5, AC-C-EXPLICIT_NONE_REQUIRED, AC-P01 and AC-R2-1 are confirmed with the coverage notes in CD02, CD06, CD03 and CD05. The 42 DEFERRED entries and the one NOT_APPLICABLE (AC-D05) are consistent with the 5.4B.1 scope. |
| 11 | Approvals | The register is unchanged: 75 rows all PENDING, SHA-256 `d86a26ce…`, matching Task 7. The addendum has 13 rows, all PENDING. R0 outputs carry 88 unique PENDING approvals with `real_project_eligible = false`. All 66 files in the Task 7 manifest are byte-identical. |
| 12 | Regressions | All 43 historical tests and Agent 1's 6 engine tests pass |

### The secondary earlier-start objective

The secondary solve runs only after a proven OPTIMAL primary. It fixes the makespan to the proven value. Status, objective, bound and gap are always taken from the primary.

I tested this by forcing the secondary solve to receive almost no time, on RC01 and R0-5. The status, objective and bound were unchanged; only the representative dates differed. With very short time limits (1 µs, 1 ms and 20 ms on R0-5, RC09 and RC01), every result was internally consistent:
- **OPTIMAL:** always validated, with bound = objective.
- **UNKNOWN:** never had a schedule; its lower bound came from the CPM relaxation.
- **FEASIBLE:** no run returned it.

The proven primary makespan cannot be invalidated or misreported. CD09 notes only that the output does not say which solve produced the dates.

### Unsupported constraints through normalized JSON

I tried 37 injections, 36 directly and 1 through `--input` on the CLI ([injection_results.csv](injection_results.csv)):

- **Rejected before solving:** every deferred or unsupported scheduling construct:
  - unknown keys at the top level and inside activities, dependencies, calendars, exceptions and deadlines;
  - non-empty reservation, event and supply fields;
  - split work, with or without authorization;
  - SS relations, working-time lags and negative lags;
  - reservation, m³/h and continuous resources;
  - `capacity_by_date`;
  - unsupported objectives;
  - tick 7;
  - real-project scope;
  - missing inputs;
  - undeclared required equipment.
- **The CLI path** exits with code 1 on non-empty reservations.
- **Accepted without effect, all nonblocking:**
  - the crew-mode fields (`reserved_without_bcca_demand`, `positive_capacity`, `demand_hours`) when `crew_mode` is absent (CD02);
  - pass-through metadata, such as approvals marked APPROVED or arbitrary fixture exceptions (CD03);
  - an unauthorized calendar exception, which correctly falls back to the default policy (CD05).

  None of these alters the schedule a solver would compute.

## Before Stage 5.4B.2 acceptance

- Fix or reclassify AC-C-V2 (CD01).
- Reject crew-mode fields without `crew_mode` (CD02).
- Validate the approval and fixture-exception metadata in the engine (CD03).
- Add the missing infeasibility diagnostic (CD04).
- Add explicit-none equipment coverage to R0 (CD06).

CD05, CD08 and CD09 are recommended reporting improvements. Stage 5.4B.2 must still meet the 42 deferred criteria, including reservations, shared supply, splits, inspection and strength events, the larger benchmark at 40,445 min and DEMO-H1 at 41,885 min.

## Reproduce

~~~powershell
& .\.venv-planning\Scripts\python.exe -B 'research/validation/stage5_4b_independent/core/scripts/verify_core.py'
& .\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_stage5_*.py'
~~~

The first command writes [case_results.csv](case_results.csv), [injection_results.csv](injection_results.csv) and [verification_results.json](verification_results.json). It takes about 4 s.
