# Stage 5.4B.1 controlled CP-SAT core

The implementation accepts fixed-duration, single-mode controlled inputs and preserves Stage 5.4A activity identities and elapsed finish-to-start edges when run from the frozen handover. It uses five-minute ticks by default and supports the fifteen-minute regression. CP-SAT minimizes elapsed makespan. After proving the minimum, it uses any remaining solve budget to prefer earlier starts at that makespan. The output reports the primary solver status, elapsed objective and lower bound in minutes, relative gap as a fraction, and combined solver wall time.

The start domains intersect the project calendar, activity windows and demanded resource calendars. Authorized exceptions replace only the project component. RC06 starts N at 07:00 under its registered authorization, and RC06-D starts N at 08:00. A cumulative constraint per demanded pool enforces simultaneous working-time units. The timestamp validator independently checks feasibility using interval endpoints and a capacity sweep. Project and activity deadlines are hard constraints, with preflight diagnostics and labelled assumptions for capacity-driven conflicts.

The frozen R0 adapter preserves the full selected crew, including the column pour's official under AP-X-CREW-01, the 28 Stage 5.4A links, the EUR 1,172.5136 direct reference cost and all 88 pending approvals. Its outcomes are OPTIMAL at 14,850 minutes and 14,880 minutes for the 5- and 15-minute runs. The reported R0 scope uses the six R2 fixture exceptions, including hypothetical passes at minimum and reservations reported as unenforced. All optimizer output is restricted to controlled use.

The automated suite checks 17 applicable reference outcomes, 13 early rejections for deferred reference constraints, both frozen-handover regressions, and reference-package hashes. Stage 5.4B.2 covers continuous reservations, shared supply, authorized splits, inspection and strength event logic, and the larger benchmark and holiday sensitivity. The [acceptance matrix](acceptance_matrix.csv) records partial evidence for criteria spanning both parts. Full Stage 5.4B acceptance requires 82 mandatory criteria.

## Reproduce from the repository root

```powershell
.\.venv-planning\Scripts\python.exe -B -m research.implementation.stage5_4b --case RC06
.\.venv-planning\Scripts\python.exe -B -m research.implementation.stage5_4b --case RC06-D
.\.venv-planning\Scripts\python.exe -B -m research.implementation.stage5_4b --frozen-r0 5
.\.venv-planning\Scripts\python.exe -B -m research.implementation.stage5_4b --frozen-r0 15
.\.venv-planning\Scripts\python.exe -B -m unittest -v research.implementation.stage5_4b.test_engine
```

The CLI also accepts `--input PATH` for normalized controlled JSON. Use the dictionary returned by `normalize_reference` or `frozen_r0` in [fixtures.py](fixtures.py) as the input shape. The CLI returns exit code 0 for a validated schedule and 1 for a diagnostic or an unverified outcome.

Baseline was clean at `6384cd329bf9bb83d0e0ff56520cc0426c69e995`. The implementation adds files under this directory. No tracked fixture or approval file was changed.

