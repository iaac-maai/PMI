# Stage 5.4B.3 architectural integration

The controlled application now runs IFC extraction, canonical BIM, work packages, engineering estimation, CPM and resource-constrained CP-SAT from one command. The optimizer lives in pmi_core/optimization and receives controlled authority through a trusted registry. The existing research CLI and imports delegate to it. The IFC and planning stages retain their separate interpreters.

| Demonstration | Result | Proof | Direct reference cost |
| --- | --- | --- | ---: |
| R0 from IFC, 5-minute tick | 14,850 min | OPTIMAL, bound 14,850 | EUR 1,172.5136 |
| R0 from IFC, 15-minute tick | 14,880 min | OPTIMAL, bound 14,880 | EUR 1,172.5136 |
| C01 original v1.1 | 40,445 min | OPTIMAL, bound 40,445 | EUR 5,103.32664 |
| C01 holiday v1.1 | 41,885 min | OPTIMAL, bound 41,885 | EUR 5,103.32664 |
| Both historical v1.0 fixtures | INFEASIBLE before solving | All four reservation coverage contradictions reported per fixture | |

The v1.1 benchmarks have zero conflicts and zero optimality gaps. Agent 2's C01 oracle passed 350 checks on each exported schedule. The application R0 outputs contain stable model, package, activity and IFC identities, with CPM timestamps and criticality distinguishable from optimized timestamps. The larger benchmark is a hypothetical schedule without IFC geometry. Its application output has no source IFC hash, IFC GlobalIds or canonical element mappings.

## Reporting corrections

F01 keeps the accepted conservative CP-SAT rate and daily limits. With Agent 2's declared 60 m3 plan and constant placement profile, the split pour reports **60 m3 planned, 3 m3 restart allowance, and 63 m3 total scheduling allowance**. The two daily plans are 24 and 36 m3. Monday's conservative allowance is 39 m3. Removing physical-volume evidence leaves that quantity unknown while preserving capacity allowance. Both restart variants retain EUR 7,114.20 direct reference cost. The optimizer neither changes engineering material quantities nor creates environmental quantities from allowances. The output now uses pmi-optimization-result/2 and rational strings for supply amounts.

F02 preserves the diagnostic code and first witness and includes every static reservation contradiction. F03 exports complete-project, conditional and unblocked-subset makespans under separate scopes. The legacy optimizer objective field still describes its solver scope. The application contract exposes no complete-project makespan for partial or conditional outcomes. F04 allows representative timestamps to differ among valid optima. F05 keeps source-fixture acceptance separate from the internal validator, which shares preparation code with the model. F06 consumes Agent 2's hash-verified C02 metadata for RC13b without rewriting Task 7. F07 records resource-local midnight to midnight, or project-local midnight to midnight for continuous pools.

## Verification

The suites passed 43 historical tests and 32 optimizer and integration tests. The relocation matched the accepted implementation at cf8f4581e65e027cd843ed42c81384a5d60224ef across 36 runs, comprising the 30 small references, two frozen R0 runs and four C01 benchmark runs. The comparison uses primary objective, bound, status and diagnostic code, validated timestamps, occupancy, reservation demands, costs and provenance. Eight historical Stage 5.4A exports reproduced byte-for-byte. Agent 2's reference packages and historical evidence were preserved. The 88 engineering approvals remain pending, real-project eligibility is false and the original R0 exclusions remain visible.

- [Architecture and module map](architecture_and_module_map.md)
- [Versioned output and pipeline contracts](integration_contract.json)
- [Output field mapping](output_field_mapping.csv)
- [Behavioural equivalence](behavioural_equivalence_results.csv)
- [F01 results and independent checker output](f01_correction_evidence.json)
- [End-to-end results and schedule paths](end_to_end_results.json)
- [Test results](test_results.json)
- [Preservation evidence](preservation_verification.json)

## Reproduce from the repository root

```powershell
$integration = 'research/implementation/stage5_4b_integration'
$planning = '.venv-planning/Scripts/python.exe'
$ifc = '.venv/Scripts/python.exe'
& $planning -B -m pmi_core.application --config "$integration/r0_config.json" --output 'outputs/stage5_4b3_r0_5' --ifc-python $ifc --planning-python $planning --tick 5
& $planning -B -m pmi_core.application --config "$integration/r0_config.json" --output 'outputs/stage5_4b3_r0_15' --ifc-python $ifc --planning-python $planning --tick 15
& $planning -B -m research.implementation.stage5_4b --demo original
& $planning -B -m research.implementation.stage5_4b --demo holiday
& $planning -B -m research.implementation.stage5_4b --demo original --benchmark-version v1.0
& $planning -B -m research.implementation.stage5_4b --demo holiday --benchmark-version v1.0
& $planning -B -m research.implementation.stage5_4b_integration.verify_integration
```

Application commands require a fresh output directory. The v1.0 commands return exit code 1 with structured diagnostics. The verification module writes only under this integration folder and uses temporary workspaces for baseline and frozen-output comparisons.
