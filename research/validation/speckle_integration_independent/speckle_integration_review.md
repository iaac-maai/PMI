# Independent Review — Speckle Integration and I04 (target: 3 December 2026)

**Reviewer:** Agent 2 (independent verifier) · **Date:** 2026-11-26 · **HEAD:** `c245e143bd7eb3f1e3e813f51c33fdb05e7397ae` (adds only my previous review files; no production change since the accepted 5.4C/5.4D state)
**Mode:** read-only. No production code, R0 artifact, approval or handover file modified. Nothing committed.
**Builds on:** [`../engineering_resource_input_independent/i04_technical_gap_analysis.md`](../engineering_resource_input_independent/i04_technical_gap_analysis.md) and `next_stage_recommendation.md` in the same folder.

## Decisions

| Capability | Decision | One-line reason |
|---|---|---|
| **Speckle model retrieval** | **CONDITIONAL GO** | Feasible, but not verifiable in this environment. It needs an authorized Speckle runtime, credentials, and a day-1 identity spike. |
| **Model normalization (Speckle → PMI canonical quantities)** | **NO-GO for 3 Dec** as a quantity source. **GO** for identity-only mapping. | Speckle IFC data is documented as mesh geometry with no quantity sets and no guaranteed `applicationId`/GlobalId equality, so quantity provenance would need new, unaccepted rules. |
| **Controlled scheduling integration** | **GO** (controlled, hypothetical inputs, IFC as source of truth) | This is I04 stages G0–G3 and the critical path. It needs no Speckle, no B1 result and no approval. |
| **Linked visualization** | **CONDITIONAL GO** | Speckle viewer selection and isolation by id exist, but the id type and IFC GUID access in 2026.9 bundles must be proven on day 1. A local-viewer fallback is mandatory. |
| **Model revision processing** | **NO-GO for 3 Dec** (stretch, report-only) | Speckle's diff view is deprecated, and the replacement is an AI feature, not an API. PMI's revision tools are legacy IFC-based oracles. |

**Recommended route: C, "Speckle visualization paired with an authenticated IFC".**
1. PMI schedules from a registered controlled IFC4 file.
2. The **same file** is uploaded to Speckle (server-side IFC import).
3. The viewer links PMI activities to Speckle objects through the IFC GlobalId recorded on each Speckle object.

This is the shortest technically sound route. It is architecture-neutral: any authoring tool that exports IFC works. It also leaves R0 authentication untouched.

Nothing here authorizes real-project scheduling or Stage 5.5. All 88 approvals stay PENDING, AP-TOL stays unset, and `real_project_eligible` stays false.

---

## 1. Existing Speckle and adapter work in the repository

| Item | Finding |
|---|---|
| `research/ifc_to_gantt/extract_elements.py:128-131` `extract_speckle()` | **Stub only.** It raises `NotImplementedError("Speckle adapter not built yet …")`. The design intent, one source-independent column schema with `source_id` = GlobalId, Revit UniqueId or Speckle `applicationId`, is reusable. |
| `research/architecture/stage5_0/repository_reuse_matrix.csv` | Speckle **IFC-Exporter** (an Automate function on specklepy 3.1.0 and IfcOpenShell; `mesh_to_ifc`, `get_ifc_guid`) is recorded as "reference only", needing an authenticated server context and Revit-shaped input. `speckle-sharp-connectors` needs host applications. |
| `research/architecture/stage5_0/existing_code_migration_matrix.csv` | Records "extract_speckle is a stub". |
| `research/ifc4d/stage3_8c_ux_report.md:75` | Lists "live Speckle version ingestion and identity matching" as **still pending**. |
| Revision tools | `research/ifc_to_gantt/compare_versions.py` and `scripts/detect_changes.py` provide legacy IFC-based element and task change comparison, keyed by `source_id`. |
| **Ahmed's architectural adapter deliverables** | **Not found** in the repository; no file or path references them. They need to be supplied before they can be reviewed. |
| Runtime | `specklepy`, `gql` and `pyarrow` are **not installed** in `.venv` or `.venv-planning`. I could not install them under the standing restrictions. |

There is no working Speckle integration today.

## 2. What Speckle model information can reliably be retrieved

The table below is based on current Speckle documentation; sources are listed at the end. It has **not been verified against a live model**, because there is no runtime or credentials here.

| Information | Documented behaviour | Reliability for PMI |
|---|---|---|
| **Identity** | IFC import stores the GlobalId in `properties."IFC GUID"` and `properties."IFC Attributes".GlobalId`. `applicationId` "may be the same as IFC GUID, but could be different". | **Reliable only via `IFC GUID`.** Never key on `applicationId` for IFC sources. For Revit-connector publishes, identity is Revit-shaped, and the GUID link is unverified. |
| **Classification** | `properties."IFC Type"` (e.g. `IfcWall`). | Reliable for IFC uploads. Connector publishes (Revit, Rhino and others) carry host categories or layers, not IFC classes. |
| **Geometry** | `displayValue` meshes with `units`. Parametric extrusions and profiles are **not documented** as preserved. | Good for **visualization**. Not acceptable as PMI's quantity source without a new mesh-volume provenance rule. |
| **Quantities** | `Qto_*BaseQuantities` **not mentioned**. Property sets are under `properties."Property Sets"`. | **Not reliable.** PMI quantities must come from the IFC itself. |
| **Materials** | RenderMaterial proxies, plus e.g. `Pset_Construction.Material` when present. | Display materials are reliable. Engineering material text depends on the exporter. |
| **Spatial containment** | Level proxies (pre-2026.9). In 2026.9, `Model` exposes accessors such as `level`. | Usable for display grouping. PMI containment comes from the IFC. |
| **Versions** | A version's `referencedObject` is a hex hash (older format) or `bundle.<project>.<model>.<version>` (2026.9). File uploads are bundles. | Version IDs are reliable provenance anchors. **Reading 2026.9 bundles requires `specklepy[bundle]==2026.9.0b3` (beta) with pyarrow. Older specklepy returns 404.** |

**Consequence:** Speckle is a reliable **visualization and version-identity layer** for an IFC-derived model. It is **not** a reliable engineering-quantity source on the evidence available.

## 3. The three integration routes

| Route | Description | Assessment | Verdict for 3 Dec |
|---|---|---|---|
| **A. Speckle → IFC conversion** | Convert Speckle objects back to IFC (e.g. Speckle IFC-Exporter) and feed PMI. | <ul><li>Lossy: mesh-to-IFC, no parametric bodies, quantities not carried.</li><li>GUIDs may be regenerated (`get_ifc_guid`).</li><li>Needs an Automate or authenticated context.</li><li>Produces a *derived* IFC that cannot be authenticated against an author's source file.</li><li>Highest risk.</li></ul> | **Reject** |
| **B. Direct Speckle → PMI intermediate** | Implement `extract_speckle` into the canonical Stage 5.1 contract. | <ul><li>Needs the beta bundle SDK.</li><li>Per-connector property mappings (IFC, Revit and Rhino shapes differ).</li><li>New quantity-provenance rules for mesh volumes.</li><li>Identity rules where `applicationId` ≠ GlobalId.</li><li>Independent acceptance of all of these.</li></ul> It is the right long-term interoperability route, but **cannot be built and accepted in one week**. | **Defer** (post-demo research; identity-only subset allowed) |
| **C. Speckle visualization + authenticated IFC** | PMI processes the registered IFC. The same file is uploaded to Speckle. The viewer maps PMI activity → GlobalId → Speckle object. | <ul><li>Reuses the whole PMI pipeline.</li><li>Quantity and identity authority stays with the hashed IFC.</li><li>Speckle adds the hosted model, version IDs and a shareable viewer.</li><li>Only new code: identity mapping and viewer linking.</li></ul> | **Recommend** |

**Revit-derived or Speckle-hosted visualization is not live synchronization.** Route C shows a **specific Speckle version** whose GlobalId set has been verified against PMI's registered IFC. Edits in Revit, Rhino or another authoring tool do **not** propagate. A new version must be exported, registered and re-run (see §8).

## 4. Shortest route to a working demonstration

The critical path is **not Speckle**; it is **I04**. No additional model can reach estimation, the worker, IFC4D or the viewer today (see the I04 analysis for line references).

The minimum working system:
1. **Controlled model (G0).** A small reinforced-concrete frame in **IFC4**: columns, beams and slabs only, one storey, about 2 bays. It can be authored in Revit or any other tool and exported to IFC, or generated by script. The file is registered by SHA-256, and Agent 2 builds the oracle before acceptance.
2. **Generalized estimation (G1)** and **generic worker (G2)** behind new entry points, with hypothetical inputs declared in a fixture manifest.
3. **Host-controlled orchestration (G3)** with input-snapshot provenance.
4. **IFC4D export for registered fixtures (G4).** This can be deferred if time runs out; see §6, item 6.
5. **Linked viewer.** The Speckle viewer embedded next to the existing SVG Gantt, linked by GlobalId. **Fallback:** the Stage 5.4D Plotly mesh viewer generalized to the registered model (G5), so the demo does not depend on Speckle availability.

### Model qualification (go or no-go before G1 starts)

The model must meet all of the following:
- **Schema and units:** IFC4, with units recorded.
- **Identities:** unique GlobalIds.
- **Classes:** only `IfcColumn`, `IfcBeam` and `IfcSlab` as physical elements, plus the spatial structure.
- **Containment:** every element contained in an `IfcBuildingStorey`.
- **Material:** a cast-in-place concrete keyword matching CR05. Otherwise UI06 blocks the element, which is correct behaviour.
- **Geometry:** closed solid bodies, with no positive-volume overlaps between elements, or overlaps explicitly declared under a stated controlled-scope rule.
- **Quantities:** authored base quantities recorded if present, but geometry volume is the controlled quantity basis.
- **Import:** a strict import that is valid, with Stage 5.2 producing one package per element and no graph issues.
- **Hypothetical inputs:** formwork area, rebar kg, crews, calendar and holds, each labelled `hypothetical_fixture` and registered in the fixture manifest.
- **No unsupported sequences:** no column `overlap` sequence, because SS edges are unsupported.

If the model comes from Revit, check these export settings: IFC4 Reference View or Design Transfer View, "Export base quantities", and "Store IFC GUID". Each is unverified until the qualification run.

## 5. I04 for a Speckle-derived model: how it reaches the scheduling engines

Under route C the Speckle layer sits **beside** the pipeline, not in it:

```
Authoring tool → IFC4 file ──(SHA-256 registered)──► PMI: 5.1 import → 5.2 packages → 5.3G estimation → G2 worker → CPM → CP-SAT → G4 IFC4D
        │                                                                                                         │
        └──► upload same file to Speckle (version V) ──► Speckle viewer ◄── GlobalId ↔ Speckle-object map ◄── PMI activity ↔ GlobalId
```

**Speckle-specific gaps added to the I04 analysis:**
- **S1:** No Speckle runtime. Needs an authorized, isolated environment with `specklepy[bundle]` 2026.9 (beta) and pyarrow, or retrieval only in the browser through the viewer.
- **S2:** No identity bridge. Build a `GlobalId → Speckle object id` map from `properties."IFC GUID"`, and record the Speckle project, model and version IDs plus the map hash in `pipeline_evidence`.
- **S3:** The viewer server is R0-only and serves local Plotly. The Speckle viewer is an additional JavaScript dependency, loaded from npm or a pinned CDN build.
- **S4:** Credentials. A token must never reach the browser bundle or the repository. Use a link-shared or public project **for the synthetic fixture only**, or a server-side proxy.
- **S5:** Version binding. Verify that the Speckle version's GUID set equals the registered IFC's GUID set before the viewer starts. Speckle does not hash the uploaded file for us.

**Reusable unchanged:** IFC import, `build_construction`, `estimate_operation`, `cpm.calculate`, the `pmi_core.optimization` package, `schedule_result`, `viewer_data`, the SVG Gantt logic in `app.js`, and the R0 trust boundary (which stays as is).

**Not reusable for the new model** (frozen for R0, generalized only behind new entry points):
- the `estimate_frame` envelope;
- `scheduling/fixture.adapt`;
- `r0_worker`, `frozen_r0` and `controlled_metadata`;
- the `ifc4d` R0 constants and allow-lists;
- the Stage 5.4D `server.py`.

## 6. Minimum acceptance criteria (independent checklist)

1. **Retrieval and identity**
   - The registered IFC SHA-256 matches.
   - The Speckle project, model and version IDs are recorded.
   - The GlobalId set retrieved from Speckle (`IFC GUID`) **equals** PMI's element GlobalId set: no missing, extra or duplicate GUIDs, and the map is 1:1.
   - The map hash is stored in provenance.
2. **Geometry**
   - PMI geometry is tessellated from the registered IFC.
   - Speckle meshes are used for display only.
   - Element counts and classes agree between IFC, PMI and Speckle.
3. **Quantities and packages**
   - Element volumes come from the actual IFC and match the Agent 2 oracle.
   - Packages and activities are generated by Stage 5.2 from this model. **No R0 constants, aliases or frozen schedule** appear anywhere: verified by code path and by hashing outputs against R0 artifacts.
   - Every hypothetical input traces to the fixture manifest.
4. **Scheduling**
   - CPM dates equal the oracle.
   - CP-SAT status, makespan and bound equal the oracle.
   - The internal validation passes.
   - Results are deterministic: identical proof values over 5 runs.
   - All 88 approvals are PENDING and `real_project_eligible` is false in every output.
5. **Negative tests**, each refused:
   - unregistered IFC;
   - modified IFC;
   - Speckle version whose GUID set differs from the IFC;
   - tampered schedule with resynced digest;
   - `engineer_approved` input;
   - SS sequence;
   - config naming an unlisted worker;
   - a real IFC from `data/raw/`;
   - R0 files substituted into the new pipeline.
6. **IFC4D**
   - Tasks equal activities, assigned to the correct GlobalIds.
   - Sequences equal dependencies, and nesting and controls are correct.
   - Round-trip verification passes.
   - The registered-fixture path cannot export R0 or unregistered models.
   - *If G4 slips:* report IFC4D as not done and demonstrate the JSON schedule only. Do not relax R0 checks.
7. **Linked visualization**
   - Clicking an element in Speckle selects its activities in the Gantt.
   - Selecting an activity in the Gantt selects and isolates its Speckle object.
   - Playback colours objects by state.
   - Viewer GUIDs resolve through the verified map only.
   - The fallback viewer passes the same checks.
8. **Restrictions visible**: the banner reads "Controlled hypothetical demonstration — not authorized for construction use", with 88 pending, eligibility false, and physical progress unverified. These texts are data-driven from the schedule.
9. **R0 preservation**:
   - R0 replay and live hashes unchanged;
   - `r0_5`/`r0_15` and `controlled_frame.ifc` hashes unchanged;
   - Stage 5.4A exports byte-identical;
   - 49 + 32 tests pass;
   - the Stage 5.4C and 5.4D verifiers pass;
   - the approval register (`d86a26ce…`) and addendum unchanged.

## 7. Linking the Speckle viewer to PMI activity IDs and selections

| Capability | Documented | Risk |
|---|---|---|
| Programmatic select | `SelectionExtension.selectObjects(ids, multiSelect)`, `unselectObjects`, `getSelectedObjects()` | The id type is **not documented** (Speckle object id vs `applicationId`). Assume the Speckle object id until proven. |
| Isolate, hide and colour | `FilteringExtension.isolateObjects`, `hideObjects`, `setUserObjectColors([{objectIds, color}])`, `resetFilters` | Selection material is reapplied on deselection and can fight colouring. Clear the selection before re-colouring (community-reported). |
| Click to element | `ViewerEvent.ObjectClicked`; selection binds to it. The payload is not documented on the extension page. | Read the object through `getSelectedObjects()` and its `properties."IFC GUID"`, which still needs a live check for 2026.9 bundles. |

**Feasible design:**
1. At load, walk the viewer's object tree.
2. Build `IFC GUID → Speckle object id`.
3. Check it against PMI's GlobalId set (criterion 1).
4. Then the Gantt drives `selectObjects` and `setUserObjectColors`, and `ObjectClicked` drives the Gantt.

**Day-1 spike (blocking):** upload the qualified IFC, load it in the viewer, and confirm that the GUID is readable and that select, isolate and colour work by the mapped ids. If the spike fails, use the fallback viewer.

## 8. Model revisions (stretch goal)

- **Retrieval:** list a model's versions and receive two versions. This uses project, model and version IDs, or bundle artifacts via `GET /api/v2/projects/{p}/models/{m}/versions/{v}/artifacts`.
- **Speckle's own comparison:** the dedicated diff view is **deprecated**, and comparison now goes through Speckle Intelligence, which needs 2026.9 data. Neither is a reproducible API. A viewer `DiffExtension` page exists in the docs index, but I have not read it.
- **Feasible stretch:**
  - compare the two versions' `IFC GUID`/class/property sets with PMI's existing `compare_versions.py` logic (ADDED, REMOVED, MODIFIED by `source_id`);
  - re-run PMI only on a **newly registered** IFC for version 2;
  - present the result as a **report**, not an automatic schedule update.
- Geometry-change detection from meshes has no accepted tolerance (AP-TOL is unset). Report it as unvalidated.

## 9. Blockers and dependencies

| Capability | Critical blockers / dependencies |
|---|---|
| Retrieval | <ul><li>User authorization for a separate environment with `specklepy[bundle]` 2026.9 beta and pyarrow (I cannot install it)</li><li>A Speckle account, project and token, handled as secrets</li><li>Network access</li><li>Whether 2026.9 bundles expose `IFC GUID` as documented</li></ul> |
| Normalization | <ul><li>Mesh-only geometry</li><li>Undocumented quantity sets</li><li>`applicationId` ≠ GlobalId</li><li>Connector-specific property shapes</li><li>Needs new provenance rules and independent acceptance, so it is out of scope for 3 Dec</li></ul> |
| Scheduling | <ul><li>I04 G0–G3 implementation by Agent 1 (new entry points, R0 frozen)</li><li>A qualified controlled IFC4 model by about 27 Nov</li><li>An Agent 2 oracle before acceptance</li></ul> No dependency on B1, AP-TOL or approvals (hypothetical scope only). |
| Linked visualization | <ul><li>A passing day-1 spike</li><li>The Speckle viewer JavaScript dependency (pinned)</li><li>A token-free or proxied load</li><li>The fallback viewer (G5) as insurance</li></ul> |
| Revisions | <ul><li>A second registered IFC version</li><li>No Speckle diff API</li><li>AP-TOL unset for geometry tolerance</li></ul> |

**Nandini's B1:** **not a dependency** for any decision above. B1 gates real-model quantity validation only. The demo model must be presented as a controlled hypothetical fixture.

## 10. Prioritized roadmap (implementation by Agent 1, acceptance by Agent 2)

| Day | Work | Owner | Exit check |
|---|---|---|---|
| **Wed 26 – Thu 27 Nov** | <ol><li>Fix and qualify the controlled IFC4 model (§4). Register its hash.</li><li>Speckle spike (§7) on that model.</li><li>Get user authorization for the Speckle environment and credentials.</li></ol> | Team / Agent 1 | Model qualified; spike pass or fail recorded |
| **27 – 30 Nov** | G1 generalized estimation and G2 generic worker (new entry points). In parallel, Agent 2 builds the independent oracle. | Agent 1 / Agent 2 | Oracle match on quantities and CPM/CP-SAT; R0 preservation |
| **30 Nov – 1 Dec** | G3 orchestration with provenance (input snapshot hash, Speckle version IDs, GUID map hash). G4 registered-fixture IFC4D. | Agent 1 | Checklist items 1–6 |
| **1 – 2 Dec** | Linked viewer: Speckle plus Gantt, with the G5 fallback viewer. Data-driven banners. | Agent 1 | Checklist items 7–8 |
| **2 Dec** | Independent acceptance run (full checklist plus negatives plus R0 preservation). Then freeze. | Agent 2 | PASS, CONDITIONAL PASS or FAIL report |
| **3 Dec** | Demonstration from the frozen, accepted build only. | — | — |

**Deferred:**
- route B normalization;
- revision processing beyond a report;
- input-capture frontend (G6);
- UI polish (5.4D U1–U6).

## Sources (Speckle documentation, consulted 2026-11-26)

- [IFC Schema — Speckle Docs](https://docs.speckle.systems/developers/data-schema/connectors/ifc-schema)
- [Object Schema — Speckle Docs](https://docs.speckle.systems/developers/data-schema/object-schema)
- [specklepy breaking changes / 2026.9 migration](https://docs.speckle.systems/next/developers/sdks/python/breaking-changes)
- [Python Operations — Speckle Docs](https://docs.speckle.systems/developers/sdks/python/api-reference/operations)
- [SelectionExtension — Speckle Docs](https://docs.speckle.systems/developers/viewer/extensions/selection-extension-api)
- [FilteringExtension — Speckle Docs](https://docs.speckle.systems/developers/viewer/extensions/filtering-extension-api)
- [GraphQL API — Speckle Docs](https://docs.speckle.systems/developers/api/graphql.md)
- [Compare versions — Speckle Docs](https://docs.speckle.systems/3d-viewer/compare-versions.md)
- [Speckle Community: retrieving ifcGUID](https://speckle.community/t/issue-retrieving-ifcguid-with-getproperties/18857)
- [Speckle Community: object data on selection (Viewer API 2.0)](https://speckle.community/t/how-to-get-object-data-on-selecting-object-in-viewer-api-2-0/7258)
