# Stage 5.4B.3 targeted independent integration acceptance

## Decision

**PASS: integration accepted and F01 closed.**

[integration_acceptance_matrix.csv](integration_acceptance_matrix.csv) has 112 rows and **110 of 110 mandatory items** are independently accepted:
- the 86 Stage 5.4B criteria as amended by C01, of which 84 are mandatory;
- the 12 Stage 5.4B.3 amendment entries;
- 14 integration task items.

**Stage 5.4C IFC4D development: authorized from the independent-verification standpoint, within the controlled scope only.** No blocking defect remains. Real-project scheduling remains **not** authorized: all 88 engineering approvals are PENDING and `real_project_eligible` is false in every output. Before Stage 5.4C accepts any input other than the registered controlled fixtures, it needs a non-fixture scheduling worker (I04).

## Baseline

- **Commit:** `e14057e06149f60b66e2c44b2a3b84fba98d045b`. HEAD and every implementation file were unchanged from start to end of the regression run.
- **Working tree:** the only change is this folder.
- **Interpreters:** OR-Tools 9.15.6755 with Python 3.12.14 (planning), and IfcOpenShell 0.9.0.post1 with Python 3.14.7 (IFC).
- **Evidence basis:** Agent 1's PASS labels and internal validator were not used as evidence. The oracles are the source-fixture checker, the exhaustive Task 4 engine, the C01 coverage checker, the independent Stage 5.4A model, and IfcOpenShell reading the IFC directly.

## F01: closed

See [f01_independent_result.json](f01_independent_result.json). Both prepared variants ran through the relocated optimizer's normal normalized-input path (research CLI `--input`, which delegates to `pmi_core.optimization.solve` with the trusted registry). They were checked by my unchanged `check_f01.py`, using a documented field map, and by level-aware checks.

| Variant | Status | Makespan | Planned placed | Restart allowance | Total allowance | Cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| A: 30-min restart, plan declared | OPTIMAL, complete project | 4,710 | 60 m³ | 3 m³ | 63 m³ | €7,114.20 |
| B: no restart, plan declared | OPTIMAL, complete project | 4,680 | 60 m³ | 0 | 60 m³ | €7,114.20 |
| A and B, evidence absent | OPTIMAL | 4,710 / 4,680 | **unknown (null)** | 3 / 0 m³ | 63 / 60 m³ | €7,114.20 |

- **Levels:** the activity, source and aggregate levels agree.
- **Daily rows:** Friday is 24 m³ planned and 24 m³ total. Monday is 36 m³ planned plus 3 m³ restart, 39 m³ in total. All other days are 0.
- **Occupancy:** restart occupancy is labelled `restart_capacity_allowance` for Monday 08:00–08:30 only.
- **No inflated or mislabelled quantities:** no measured, actual, consumed, material or environmental field carries an allowance, and supply provenance is never `independently_measured`. The engineering quantity and the €7,114.20 cost are unchanged, and the allowance-inflated €7,469.91 never appears.
- **Unknown stays unknown:** with no declared plan, the planned volume is null at every level. The prepared checker fails exactly its "placed volume reported" check, as intended (I09).

## Architecture

- `pmi_core/optimization/model.py` is the **only** CP-SAT model builder in the repository.
- The research `engine.py`, `advanced.py`, `capacity_dates.py` and `input_states.py` are 2–18-line delegating wrappers. A runtime probe confirms that the research `solve` calls `pmi_core.optimization.engine.solve` with a `ControlledRegistry`.
- Neither `pmi_core/optimization`, `pmi_core/application.py` nor `pmi_core/schedule_result.py` imports research modules, and the application contains no research or fixture paths.
- **Authority comes only from the trusted registry:**
  - `solve` without a registry raises TypeError.
  - The default registry denies the RC06 calendar exception (N falls back to 08:00) and the R0 fixture exceptions.
  - A registry containing an APPROVED row is rejected.
- **Requests cannot bypass the gates.** Each of these is rejected with no schedule and no eligibility: a request-supplied `registry`, an APPROVED approval row, a real-project scope, `real_project_eligible: true`, unregistered fixture exceptions, and `engineer_approved` states.
- **Interpreter separation:** IFC and estimation run in the IFC interpreter, CPM and CP-SAT in the planning interpreter. The orchestrator loads neither IfcOpenShell nor OR-Tools.

## End-to-end IFC pipeline

See [end_to_end_verification.json](end_to_end_verification.json).

| | 5-minute tick | 15-minute tick |
| --- | --- | --- |
| Status and scope | OPTIMAL, complete project | OPTIMAL, complete project |
| Makespan and bound | **14,850** | **14,880** |
| Direct reference cost | €1,172.5136 | €1,172.5136 |
| Independent Stage 5.4A check | no errors | no errors |

**Identities**
- The source IFC SHA-256 `8932ed0e…` is the same in the file, the evidence and the registered configuration.
- The canonical model ID matches the handover.
- The stage payload hashes equal the produced files.
- The three IFC GlobalIds, read directly with IfcOpenShell, each map to exactly 7 of the 21 activities.

**Structure**
- There are 3 work packages and 28 dependencies, with every endpoint mapped.
- Package and activity IDs are identical across both resolutions and equal the pipeline handover's IDs.

**Baseline and optimized schedules**
- CPM and optimized timestamps are separate fields, and only the baseline carries `cpm_critical`. The values coincide for R0 (I05).
- The FX-R0-01 to 06 exclusions are preserved.

**Derivation.** The pipeline's IFC-derived handover is byte-identical to the frozen Stage 5.3A handover, which is expected. To prove the worker actually consumes it, I doubled one productive duration in a copy: the worker rejected it. A configuration with a wrong IFC hash stops before any stage runs.

## Behavioural equivalence: 36/36

See [behavioural_equivalence_verification.csv](behavioural_equivalence_verification.csv). I re-ran my accepted Stage 5.4B.2 oracle against the relocated code; this was not a new reference suite.

- **30 small cases:** all pass the independent per-minute checks.
- **2 frozen R0 runs:** 14,850 and 14,880 min, matching the independent model.
- **v1.1 benchmarks:** OPTIMAL at 40,445 and 41,885 min, with bound = objective. Each passes 350/350 C01 checks, including 108 coverage checks, with zero conflicts and €5,103.32664. CPM: 16,310 min, 29 conflicts, 11 pools.
- **v1.0 benchmarks:** rejected before solving, listing **all four** R-COLSET-C1..C4 contradictions.

Representative dates are not required to match. The larger benchmark has no IFC hash, GlobalIds or element mappings, in either the fresh unified output or the committed export.

## Output safety, amendments and criteria

- **Scopes:**
  - **Complete-project schedules** set `project_makespan_minutes`; RC01, for example, is 1,610.
  - **Conditional outcomes** (RC12b, RC13b) and **unblocked-subset outcomes** (RC12c) leave `project_makespan_minutes` null and report only their scoped makespan.
  - **Infeasible and invalid outcomes** (RC07a, RC08a) have no makespan.
  - The application exits with 1 unless the scope is complete project.
- **C02:** RC13b carries `HYP-RC13B-PLANNED-STRENGTH-TEST-CRITERION`, taken from the hash-verified v1.1 case. The outcome is unchanged: CONDITIONAL, 5,880 min.
- **C03:** a London resource changes at London midnight. Madrid DST days span 1,380 and 1,500 minutes. Invalid overrides are rejected, and all dated scenarios equal my independent enumeration.
- **Stage 5.4B criteria:** all 84 mandatory criteria remain independently accepted ([regression/](regression/)).

## Regression and preservation

See [preservation_verification.json](preservation_verification.json).

- **Tests:** 43/43 historical tests and 32/32 optimizer and integration tests pass.
- **Frozen exports:** the 8 Stage 5.4A exports are byte-identical.
- **Approvals:** the register is unchanged (`d86a26ce…`), with 88 PENDING.
- **Manifests:** the Task 7 manifest (66 files), the C01 manifest (15 files), the v1.0 hashes, the final Stage 5.4B.2 package (9 files) and the integration-prep files are all unchanged.

## Discrepancies

None is blocking. See [discrepancy_register.csv](discrepancy_register.csv).

**Resolved**
- **I01:** F01, the split-pour supply reporting.
- **I02:** the full list of structural contradictions (former F02).
- **I03:** the scoped makespans (former F03).

**Nonblocking**
- **I04:** the registered R0 worker is research-based and fixture-gated. Stage 5.4C needs a production worker before accepting other inputs.
- **I05:** the R0 optimized dates equal the CPM dates.
- **I06:** the internal validator still shares preparation code with the model (carried F05).
- **I07:** representative dates may vary between runs (carried F04).
- **I08:** the legacy optimizer `objective_minutes` is reported for every scope, so consumers must use the unified proof fields.
- **I09:** the F01 declared-plan inputs are a documented addition to the prepared scenario.

## Reproduce

Run from the repository root:

~~~powershell
$s = 'research/validation/stage5_4b_independent/integration_final/scripts'
$env:PYTHONHASHSEED = '0'
& .\.venv-planning\Scripts\python.exe -B "$s/verify_regression.py"
& .\.venv-planning\Scripts\python.exe -B "$s/build_regression_matrix.py"
& .\.venv-planning\Scripts\python.exe -B "$s/verify_f01.py"
& .\.venv-planning\Scripts\python.exe -B "$s/verify_e2e.py"
& .\.venv-planning\Scripts\python.exe -B "$s/verify_safety.py"
& .\.venv-planning\Scripts\python.exe -B "$s/build_package.py"
~~~

`verify_regression.py` and `build_regression_matrix.py` are adapted copies of the accepted Stage 5.4B.2 oracle. The originals in `final/` are unchanged.

No production code was modified. IFC4D was not developed. Nothing was installed, trained, approved, committed or pushed.
