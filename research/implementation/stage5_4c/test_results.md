# Stage 5.4C test results

| Check | Result |
|---|---|
| Focused IFC4D unit tests | 6 passed after C1 closure |
| Historical Stage 5 tests | 43 passed |
| Stage 5.4B optimizer and 5.4B.3 integration tests | 32 passed |
| Live R0 pipeline with IFC4D, 5-minute resolution | PASS, 14,850 minutes |
| Live R0 pipeline with IFC4D, 15-minute resolution | PASS, 14,880 minutes |
| Source geometry and IFC element GlobalIds | Identical world-coordinate vertices and faces for all three elements in both rounds |
| IFC4 structural validation and PMI round trip | PASS for both resolutions, with 73 source instances, 3 packages, 21 activities, 21 assignments and 28 dependency edges |
| Scope and output guards | C01, arbitrary IFC, altered approvals, incomplete dependencies, forged dates and missing provenance rejected. Existing output preserved. |
| Preservation against accepted commit `ee9676a` | No tracked differences in the optimizer, scheduling modules, frozen Stage 5.4A or 5.4B artifacts, engineering approval materials, or independent acceptance packages |

Both live results matched their accepted R0 artifacts for all activity rows, package rows, dependency rows, CPM data, pending approval rows, fixture exclusions, direct cost, eligibility and project makespan. The project makespans matched their lower bounds. The IFC adapter used IfcOpenShell 0.9.0.post1. The planning run used OR-Tools 9.15.6755.

## Reproduce

Run the focused and historical tests with the IFC interpreter.

```powershell
& .\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_ifc4d_r0.py'
& .\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_stage5_*.py'
```

Run optimizer and integration tests with the planning interpreter.

```powershell
& .\.venv-planning\Scripts\python.exe -B -m unittest `
  research.implementation.stage5_4b.test_engine `
  research.implementation.stage5_4b.test_advanced `
  research.implementation.stage5_4b.test_review `
  research.implementation.stage5_4b.test_closure `
  research.implementation.stage5_4b_integration.test_integration
```

Run each live pipeline resolution with a fresh output directory.

```powershell
foreach ($tick in 5, 15) {
  & .\.venv-planning\Scripts\python.exe -B -m pmi_core.application `
    --config research/implementation/stage5_4b_integration/r0_config.json `
    --output "r0-ifc4d-live-$tick" --tick $tick --ifc4d `
    --ifc-python .\.venv\Scripts\python.exe `
    --planning-python .\.venv-planning\Scripts\python.exe
}
```
