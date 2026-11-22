# Stage 5.4B.3 acceptance: re-confirmation at `ee9676a`

The 5.4B.3 acceptance in this folder (`integration_acceptance_report.md`) verified commit `e14057e`. HEAD is now `ee9676ad122fe8d8dc53efde41cbcb45baf9128f`.

The only change since `e14057e` is that this acceptance package was committed. `git diff e14057e ee9676a` is **empty** for all of these:
- `pmi_core/`
- `research/implementation/`
- `tests/`
- `research/validation/engineering_approval_review/`
- `research/validation/stage5_4a_independent_verification/`

The production optimizer, application and adapters are therefore byte-identical to the accepted implementation.

## Spot-checks re-run at `ee9676a`

| Check | Result |
| --- | --- |
| Historical tests | 43/43 OK |
| Optimizer and integration tests | 32/32 OK, including `stage5_4b_integration.test_integration` |
| F01 live run (production CLI, normalized input, declared-plan variants) checked with the unchanged `check_f01.py` | PASS. A: 60 m³ planned, 3 m³ restart allowance, 63 m³ total allowance, 4,710 min. B: 60 / 0 / 60 m³, 4,680 min. Cost €7,114.20 in both. |
| Working tree | Only Agent 1's untracked `research/implementation/stage5_4b_integration/resource_handover/` (three CSV documents, imported by no code); not part of the accepted implementation |

All other evidence is unchanged and applies as recorded:
- 36/36 behavioural equivalence cases;
- R0 end-to-end from the IFC at 14,850 and 14,880 min, €1,172.5136;
- the C01 benchmarks at 40,445 and 41,885 min, with both v1.0 fixtures rejected listing all four contradictions;
- 8/8 Stage 5.4A exports byte-identical;
- 88 approvals PENDING;
- `real_project_eligible` false everywhere.

## Decision

**PASS: integration accepted and F01 closed.** This is unchanged from the `e14057e` acceptance and holds for `ee9676a`.

**Stage 5.4C IFC4D development is authorized within the controlled scope.** Real-project scheduling is not authorized. Before Stage 5.4C accepts any input other than the registered controlled fixtures, it needs a production scheduling worker (finding I04).
