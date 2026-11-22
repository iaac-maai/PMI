# PMI R0 controlled frontend

From the repository root, use the existing IFC environment. It supplies IfcOpenShell and Plotly. The prototype uses a local WebGL-capable browser.

```powershell
& .\.venv\Scripts\python.exe -B -m research.implementation.stage5_4d.server --tick 5
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). Use `--tick 15` for the other accepted replay or `--port` if the default port is occupied. Stop the server with Ctrl+C.

To inspect a fresh application bundle, use a new output directory.

```powershell
& .\.venv-planning\Scripts\python.exe -B -m pmi_core.application `
  --config research/implementation/stage5_4b_integration/r0_config.json `
  --output outputs/r0-frontend-run --tick 5 --ifc4d `
  --ifc-python .\.venv\Scripts\python.exe `
  --planning-python .\.venv-planning\Scripts\python.exe
& .\.venv\Scripts\python.exe -B -m research.implementation.stage5_4d.server `
  --run-dir outputs/r0-frontend-run
```

Click an IFC element or its keyboard-accessible selector to mark its seven rows. Click or press Enter on a Gantt row to highlight the element and inspect the exact dates. Use the Plotly toolbar for orbit and pan, and the camera controls for zoom and reset. The package filter limits visible rows and hides edges whose endpoints are outside that package. CPM outlines critical activities and CP-SAT uses the accepted optimized bars. Scrub or play the optimized schedule to see simulated activity states. Selected elements remain teal during playback.

- [Architecture and data flow](architecture.md)
- [Frontend data contract](data_contract.md)
- [Test results and preservation evidence](test_results.md)
- [Linked overview screenshot](screenshots/r0-overview.png)
- [Filtered playback screenshot](screenshots/r0-playback.png)

## Known limitations

- Scope is restricted to the three-element R0 IFC and its two accepted schedule resolutions. All 88 engineering approvals are pending and construction use is prohibited.
- The local app serves tessellated geometry through Plotly.js. A compatible browser needs WebGL. External IFC viewer compatibility and IFC EXPRESS rules were outside this check.
- Live bundle matching depends on the deterministic Stage 5.4C output bytes. Use the accepted IFC environment for generation and loading.
- The Gantt uses an elapsed-time axis and minimum-width short bars for visibility. Exact start and finish dates appear in the activity details. Calendar shading, resource occupancy and a separate critical-edge overlay are outside the prototype.
- Amber and green show simulated activity states. A green element means all seven linked activities have reached their scheduled finish. Physical progress is unverified. At 1× playback advances 420 simulated minutes per real second.
