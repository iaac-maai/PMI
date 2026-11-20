# Correction C01: column formwork reservation coverage (fixture v1.1)

**Decision for the corrected benchmark inputs: PASS.**

The v1.1 original and holiday fixtures are internally consistent and differ from v1.0 only in the four column coverage lists. Each was independently recomputed to a proven optimum:

| Fixture | Result | Completion | Proof |
| --- | --- | --- | --- |
| Original | **40,445 min** | 1 March 2027 10:05 | Lower bound equals the schedule |
| Holiday | **41,885 min** | 2 March 2027 10:05 | Lower bound equals the schedule |

- **Cost:** €5,103.32664, unchanged.
- **Checks:** every check passes, including 108 coverage checks per fixture.
- **Historical fixtures:** both v1.0 fixtures are preserved and are now provably rejected.

## 1. The contradiction is confirmed, and the error was mine

In both v1.0 fixtures, `R-COLSET-C1`..`C4` open at `C*-FORM` start and list `C*-REBAR` as covered. The cage-first rule (`C*-REBAR → C*-FORM`, AP-DR05) makes REBAR finish no later than FORM starts. A positive-duration REBAR activity therefore lies outside every possible reservation interval. This violates contract rule V8 ([resource_contract.json](../../resource_contract.json): "every working segment of covers_activities must lie inside [start_event, release]").

**Cause.** The Task 6 builder assigned the same seven covered activities to every element. My Task 6 checker and scheduler never read `covers_activities`, so v1.0 was reported OPTIMAL at 40,445 min. Agent 1's report of INFEASIBLE is correct for v1.0.

## 2. The correct semantics for cage-first

Under the declared method, the column cage is fixed **before** the formwork set is erected around it. The set is therefore neither occupied by, nor needed for, the cage work. The reservation correctly opens at FORM start and runs to STRIP finish, covering FORM, INSP, POUR, CURE, STRIKE and STRIP.

Beams and slabs are formwork-first, so their REBAR happens inside erected formwork and remains covered. This is a reference correction, not an engineering approval. Whether sets must be reserved earlier, for delivery or handling, stays with the pending AP-X-FW-03.

## 3–4. The corrected fixtures, with history preserved

| Fixture | v1.0, preserved unchanged | v1.1, corrected |
| --- | --- | --- |
| Original | `controlled_resource_demo/fixture_inputs.json` `1b9df094…` | [original/fixture_inputs_v1.1.json](original/fixture_inputs_v1.1.json) `1d465b1e…` |
| Holiday | `controlled_resource_demo_holiday_sensitivity/fixture_inputs.json` `4b166b42…` | [holiday/fixture_inputs_v1.1.json](holiday/fixture_inputs_v1.1.json) `0fa8b4fc…` |

All v1.0 fixtures, schedules, reports, Task 7 acceptance criteria and manifests are untouched; their hashes match the Task 7 manifest. Each v1.1 file carries a `_meta.correction` block with the superseded path, hash, change and rationale. Full hashes are in [correction_manifest.json](correction_manifest.json).

## 5–6. The checker is corrected, and it rejects the originals

[scripts/correct_and_verify.py](scripts/correct_and_verify.py) adds two checks to the Task 6 checks (calendars, durations, precedence, strike from pour, per-minute capacity including reservations):

- **`check_with_coverage()`**, a timestamp check: every declared covered activity must lie within [start event, latest release + return lead].
- **`static_coverage()`**, a precedence check: a covered activity that precedes the start-event activity, or follows a release activity, is a contradiction for any schedule.

| Fixture / schedule | Checks | Failed | Static contradictions | Verdict |
| --- | ---: | ---: | ---: | --- |
| Original v1.0 + its committed schedule | 354 | 4 (C1–C4 REBAR coverage) | 4 | **REJECTED** |
| Holiday v1.0 + its committed schedule | 354 | 4 | 4 | **REJECTED** |
| Original v1.1 + the same historical schedule | 350 | 0 | 0 | ACCEPTED |
| Holiday v1.1 + the same historical schedule | 350 | 0 | 0 | ACCEPTED |

The static result proves v1.0 is infeasible for **every** schedule, not just the committed one ([checker_results.csv](checker_results.csv)).

## 7. Independent recalculation from the v1.1 JSON alone

The recalculation reads only the corrected JSON. Resources and calendars are compared against the engine constants, not assumed to match them. It uses my own Task 6 engine, which has no Agent 1 code: an exact reservation-disjunction lower bound plus serial schedule generation. It runs with `PYTHONHASHSEED=0`, and reruns are byte-identical.

| | Original v1.1 | Holiday v1.1 |
| --- | ---: | ---: |
| Status | OPTIMAL (lower bound = schedule) | OPTIMAL (lower bound = schedule) |
| Makespan | 40,445 min | 41,885 min |
| Completion | 2027-03-01 10:05 | 2027-03-02 10:05 |
| CPM | 16,310 min, 29 conflicts, 11 pools | same |
| Cost | €5,103.32664 | €5,103.32664 |
| Checks failed | 0 of 350 | 0 of 350 |

These match the expected values, and they also match Agent 1's in-memory coverage-sensitivity runs. That agreement is a comparison, not the basis of this result.

## 8. Exact changes, and confirmation that nothing else changed

[fixture_diff.json](fixture_diff.json) shows exactly four changed paths in each fixture, `reservations[0..3].covers_activities`. Each removes one item, `C1-REBAR` to `C4-REBAR`; for example, C1 goes from FORM, REBAR, INSP, POUR, CURE, STRIKE, STRIP to FORM, INSP, POUR, CURE, STRIKE, STRIP.

These sections are byte-equal between v1.0 and v1.1:
- resources and crew modes;
- calendars;
- activities, including all durations and costs;
- the 98 dependencies;
- elements, supports and work packages;
- supply, holds, split policy and project;
- every other reservation field.

## 9. Versioned updates to the manifest and criteria

- **[acceptance_criteria_amendment_v1.1.csv](acceptance_criteria_amendment_v1.1.csv):**
  - **Amended:** AC-D01 to AC-D04, AC-DEMO-H1 and AC-C-V8. V8 gains a static, pre-solve contradiction test.
  - **New:** AC-C01-H, under which the historical fixtures must never yield a schedule, and AC-C01-M, under which acceptance uses the v1.1 inputs.
- **[correction_manifest.json](correction_manifest.json):** the preserved v1.0 hashes, the v1.1 hashes, the supersession mapping and `benchmark_inputs_for_acceptance`.
- The original `acceptance_criteria.csv` and `deliverable_manifest.json` are unchanged.

## 10. Other reservations

The analysis covered all 224 covered-activity entries, 112 per historical fixture across 16 reservations ([coverage_analysis.csv](coverage_analysis.csv)):
- 216 are implied by precedence.
- The only contradictions are the 8 column REBAR entries.

Beam and slab sets and props are correct as declared. Task 4 RC05a/b declare no coverage lists, and their FORM-to-STRIP spans contain no rebar. No other reference file declares `covers_activities`.

## Open items

These are recorded in [discrepancy_register_C01.csv](discrepancy_register_C01.csv):
- **C01-4:** the unchanged Task 6 builder would regenerate the v1.0 coverage, so it must not be used to rebuild the benchmark.
- **C01-5:** the reservation-timing engineering decision remains with AP-X-FW-03, PENDING.

`research/implementation/stage5_4b/fixtures.py` showed an uncommitted change during this review. It is Agent 1's concurrent work; I neither modified nor reviewed it.

No production optimizer code was modified, nothing was approved, installed, trained, committed or pushed, and all 88 approvals remain PENDING.

## Reproduce

~~~powershell
& .\.venv\Scripts\python.exe -B 'research/validation/stage5_4a_independent_verification/corrections/C01_column_reservation_coverage/scripts/correct_and_verify.py'
~~~

The script sets `PYTHONHASHSEED=0` itself and takes about 8 s.
