# Stage 5.4B.3 targeted acceptance preparation

This folder prepares narrow, independent checks for integration acceptance. It does **not** run the production optimizer: Agent 1 is still correcting F01 and relocating the optimizer to `pmi_core/optimization/`.

## Contents

| Item | Purpose | Status |
| --- | --- | --- |
| [F01_split_pour_supply/](F01_split_pour_supply/) | Regression for the split-pour supply reporting finding | Scenario, inputs and checker ready. Self-test passes. |
| [../../stage5_4a_independent_verification/corrections/C02_rc13b_acceptance_criterion_ref/](../../stage5_4a_independent_verification/corrections/C02_rc13b_acceptance_criterion_ref/) | RC13b v1.1 adds the R2-3 `acceptance_criterion_ref` | The only difference is that field. The independent recomputation is unchanged: CONDITIONAL, 5,880 min. |
| [../../stage5_4a_independent_verification/corrections/C03_capacity_by_date_timezone/](../../stage5_4a_independent_verification/corrections/C03_capacity_by_date_timezone/) | Narrow contract amendment R3-F07 for date-capacity timezones | Written, with `zoneinfo`-computed examples |
| [acceptance_criteria_amendment_5_4B3.csv](acceptance_criteria_amendment_5_4B3.csv) | 12 versioned criteria for integration acceptance | AC-F01-1..7, AC-RC13b (C02), AC-C03-1..3, AC-INT-P1 |
| [prep_manifest.json](prep_manifest.json) | Hashes of every new file, plus preservation checks of all originals | All originals unchanged |

## F01: what is checked

The scenario is RC10a's 600-minute split activity, made a pour drawing 6 m³/h with a 30-minute restart and costed at the BCCA 05HHL00003 price. Variant B is identical except for a 0-minute restart. The checker recomputes everything from the returned segment timestamps, then requires the following:

- **Volumes:** the output distinguishes three quantities.
  - **60 m³ planned placed volume:** 24 m³ on Friday and 36 m³ on Monday.
  - **3 m³ restart allowance:** on Monday.
  - **63 m³ total conservative supply allowance:** labelled as an allowance. On Monday the total is 39 m³.
- **No measurement labels:** no field named measured, consumed, actual, exact or as-built carries an allowance-inclusive value, and the supply outputs are not marked `independently_measured`.
- **Occupancy labels:** restart occupancy has its own basis, distinct from placement working time.
- **Cost:** the direct reference cost is €7,114.20 (60 m³ × €118.57) in both variants. The allowance-inflated €7,469.91 must never appear.
- **Schedule:** A is 4,710 min, with segments Friday 12:00–16:00 and Monday 08:00–14:30. B is 4,680 min.

Field names are configurable with `--field-map`, so Agent 1's chosen names can be used; the semantics are fixed.

The self-test shows three outcomes:
- the corrected output shape passes;
- the `d72eda3` shape is rejected on four checks: no placed volume, no separate allowance, a measurement-labelled 39 m³ day total, and unlabelled restart occupancy;
- an allowance-inflated cost is rejected.

## Run after the integrated commit is stable

```powershell
$d = 'research/validation/stage5_4b_independent/integration_prep/F01_split_pour_supply'
# 1. Run the integrated CLI's normalized --input path on $d/inputs/f01_A_restart_30.json and f01_B_restart_0.json; save A.json and B.json
# 2. Check:
& .\.venv-planning\Scripts\python.exe -B "$d/check_f01.py" --result-a A.json --result-b B.json --report "$d/f01_result.json" [--field-map MAP.json]
```

No production code was modified. Nothing was approved, installed, trained, committed or pushed.
