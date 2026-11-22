# Stage 5.4C conditional acceptance closure

## C1 schedule integrity

Standalone export authenticates the exact committed 5-minute and 15-minute R0 schedule artifacts against SHA-256 values registered in the adapter. Git LF and CRLF checkout representations are accepted. The IFC provenance and round-trip evidence record the SHA-256 of the actual bytes consumed. Standalone replay requires one of the two registered artifacts.

For live exports, the application hashes the schedule bytes it receives from the planning worker, records the digest in `pipeline_evidence.json` and passes it to the IFC runtime. The IFC runtime also compares a canonical SHA-256 against the registered accepted R0 schedules. Canonicalization excludes the four solver runtime measurements and interpreter metadata. It retains the IFC input and stage provenance, activity rows, dates, proof, dependencies, approvals and other schedule output.

Both paths validate against the registered project start of 2027-01-04 at 08:00 +01:00. They check the latest finish against the reported project makespan and verify that an optimal result has the same lower bound and zero gap. Each optimized interval must match its segment, reported working and elapsed minutes, and the accepted R0 durations. These checks run before any IFC4D bundle is published.

## Verification

- The six focused IFC4D tests passed. They reproduce the standalone forgery by moving the final activity and its segment one day while keeping the reported proof unchanged. The timing check rejects it. Adjusting the makespan alone fails the optimality check. Adjusting the lower bound and scoped makespan as well fails authentication. A matching caller-generated digest also fails the live content check.
- Standalone replay succeeded for both registered schedules. World-coordinate tessellation and source GlobalIds matched at both resolutions. C01, an altered IFC, altered approval status, incomplete dependencies, modified activity durations, missing provenance and an incorrect application digest were rejected. Existing output was preserved.
- The 5- and 15-minute application runs reproduced the accepted schedules at 14,850 and 14,880 minutes. All 88 approval rows were PENDING and eligibility was false. The schedule bytes matched the digest in pipeline evidence and IFC round-trip provenance.
- Historical and integration regressions passed, with 43 and 32 tests respectively.
- The source IFC, accepted schedules, frozen Stage 5.4A and 5.4B evidence and approvals were preserved. The 5-minute IFC, viewer JSON and round-trip evidence retain the bytes from the conditional acceptance review. Agent 2's report was preserved. Its checkout SHA-256 was `d9d2bab3b5033e26f7c2f49583ae9c469313034386dc9695e807106d97c45e94`.

## C2 commit scope

The Stage 5.4C commit contains `pmi_core/application.py`, `pmi_core/adapters/ifc4d.py`, `pmi_core/viewer_data.py`, `tests/test_ifc4d_r0.py` and these seven files under `research/implementation/stage5_4c/`: `closure_report.md`, `field_mapping.csv`, `implementation_report.md`, `round_trip.json`, `scheduled.ifc`, `test_results.md` and `viewer.json`. The resource handover and independent validation files are outside the commit.

## Independent reconfirmation

1. Check out the closure commit and record its hash and changed paths with `git show --format=fuller --name-status HEAD`. Hash the checked-out implementation files using the command below and record the resulting SHA-256 values as the verified revision. The application, adapter and focused tests intentionally differ from the conditional review; the viewer builder and example bundle retain the reviewed content.
2. Run the commands in [test results](test_results.md), which include the focused forgery reproduction and both live application runs. Re-run Agent 2's existing verifier to apply its separate IFC and scheduling oracles. The forged-case CLI exit must now be 1 and the standalone diagnostic must report the makespan mismatch.
3. Compare each live `schedule.json` SHA-256 with `stage_payload_sha256.schedule` in `pipeline_evidence.json` and `provenance.ScheduleSha256` in `ifc4d/round_trip.json`. Confirm 73 original STEP instances, three source GlobalIds, 21 timed activities, 28 sequences, 88 approvals pending and eligibility false.
4. Confirm preservation with the baseline diff below. Check the example artifact hashes against the values that follow. Raw checkout digests assume the same line endings as the conditional review.

```powershell
Get-FileHash pmi_core/application.py, pmi_core/adapters/ifc4d.py, pmi_core/viewer_data.py, tests/test_ifc4d_r0.py
git diff --exit-code ee9676a HEAD -- pmi_core/optimization pmi_core/scheduling pmi_core/estimation pmi_core/construction pmi_core/schedule_result.py research/planning research/implementation/stage5_2 research/implementation/stage5_3 research/implementation/stage5_4a research/implementation/stage5_4b research/implementation/stage5_4b_integration research/validation
Get-FileHash research/implementation/stage5_4c/scheduled.ifc, research/implementation/stage5_4c/round_trip.json, research/implementation/stage5_4c/viewer.json
```

| Example artifact | SHA-256 |
| --- | --- |
| `scheduled.ifc` | `c50a585e4b88fedeea1ef11d6af67d504bcda24f63d33779c891c05c22d487b1` |
| `round_trip.json` | `dff6b2138c09ef92d7373f019a388212a6f979d7f171ba15cac5502e9af88fc4` |
| `viewer.json` | `7714a97804333d26e962d39d26448418437e00c521b496c3d4b7f5d1d8b7c93d` |

Frontend development remains paused for independent reconfirmation.
