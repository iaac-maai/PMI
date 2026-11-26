# Independent Review — Engineering Resource Input Architecture

**Reviewer:** Agent 2 (independent verifier) · **Date:** 2026-11-26
**Reviewed:** `research/planning/engineering_resource_input_feasibility/architecture_proposal.md` (SHA-256 `5f43a521…0f305`) and `field_mapping.csv` (`2a203757…cb67`)
**Repository:** HEAD `5b491e834fbcab5e4bc87e6816a6e7e667423bfa`. No production change since the accepted Stage 5.4C/5.4D state; the latest commit adds only the proposal, Nandini's workbooks and my intake report.
**Mode:** read-only. No production code, R0 artifact, frontend, approval or handover file was modified.

Companion deliverables:
- [`field_mapping_verification.csv`](field_mapping_verification.csv)
- [`i04_technical_gap_analysis.md`](i04_technical_gap_analysis.md)
- [`next_stage_recommendation.md`](next_stage_recommendation.md)
- [`verification_manifest.json`](verification_manifest.json) (file hashes)

---

## Decisions

| Item | Decision |
|---|---|
| **Architecture proposal** | **CONDITIONAL PASS.** The separation model is sound and consistent with the runtime. Six conditions (A1–A6) must be added before any implementation of an input service. |
| **Field mapping (22 inputs)** | **CONDITIONAL PASS.** All IDs, labels, units and B6 destinations are correct. Results: 7 PASS, 11 PASS with note, 4 CONDITION (UI08, UI12, UI17, UI19). An implementation-status dimension is missing. |
| **Controlled I04 development** | **May begin**, on registered synthetic fixtures only. See `next_stage_recommendation.md`. |

Nothing here authorizes real-project scheduling. All 88 approvals remain PENDING, AP-TOL is unset and `real_project_eligible` remains false.

---

## 1. What the proposal gets right (verified against code)

| Claim in proposal | Verification |
|---|---|
| The runtime rejects request-supplied `engineer_approved`, so a frontend approval toggle cannot work | **True.** `pmi_core/optimization/input_states.py:61` raises `UNVERIFIED_APPROVAL` for any `engineer_approved` state. |
| Registry authority must come from the host service | **True.** `ControlledRegistry` (`registry.py:15-21`) is documented "Do not construct it from solver request JSON". `check_metadata` requires 88 unique PENDING rows and rejects any supplied approval list that differs (`registry.py:24-47`). |
| `missing` blocks; blank is never zero; explicit false is a decision | **Consistent** with `input_states.py:62`, estimation `blockers`, and Stage 5.2 `quantity_missing` blockers (probe: 8 of 10 activities on a non-R0 IFC). |
| `user_provided_project` and `independently_measured` need evidence | **Partially enforced.** The runtime requires only a non-empty `evidence_ref` string (`input_states.py:63-66`). See A2. |
| Hypothetical fixture values stay in a fixture namespace | **Policy only.** Nothing in code enforces it. See A1. |
| Independently measured differs from engineering approval | **Correct**, and consistent with the B1 intake: Revit-on-IFC measurement is a reference cross-check, not ground truth and not approval. |
| Current R0 viewer and exporter stay R0-only | **True.** `adapters/ifc4d.py` hard-codes R0 hash, model, start, counts and hash allow-lists. `stage5_4d/server.py` hard-codes 3 GlobalIds and ticks 5/15. |
| The B6 crosswalk gives a usable vocabulary | **True.** 22/22 IDs and 24/24 contract objects matched (intake report §3). |
| 13 AP-X addendum rows plus 75 register rows | **True.** 88 IDs, all PENDING. Both register files are unchanged (`d86a26ce…`, `fdc1e1ce…`). |

### Separation check (Priority 2)

| Layer | Represented in proposal | Enforced in current code |
|---|---|---|
| User-provided drafts | Yes (draft namespace, `user_provided_project`) | Input state exists; no draft store exists |
| Hypothetical fixture values | Yes (fixture namespace, visibly marked) | Input state exists; **scope is self-declared** by the request (`scope == "hypothetical_fixture_only"`) |
| Independently measured quantities | Yes (tool, units, model revision, method) | Input state exists; evidence unverified |
| Evidence verification | Yes (distinct record) | **Not implemented**: `evidence_ref` is free text |
| Engineering authorization | Yes (reviewer, authority, signed reference, scope) | Runtime refuses all authorization (correct for now) |
| Scheduling eligibility | Yes ("before any eligibility decision") | Hard false everywhere (`schedule_result.py:75`, optimizer result, estimation) |
| Derived scheduling outputs | Yes (read-only projections) | `schedule_result` and `viewer_data` are derived only |

**Bypass assessment.** No frontend field or user-supplied flag can produce an approved or real-project-eligible schedule with the current runtime:
- `engineer_approved` is rejected.
- Approval metadata must equal the host registry's 88 PENDING rows.
- `real_project_eligible` is constant false.
- Calendar-exception authorizations are honoured only when the registry recognises the exact registered entry; others are listed as ignored.

Four weaker points remain, and become relevant as soon as an input service exists:
1. **Scope-label laundering.** The solver accepts any request that declares `scope: "hypothetical_fixture_only"`. It cannot distinguish genuine project data relabelled as a fixture.
2. **Free-text evidence.** A `recorded_pass` strength or inspection event with any non-empty `evidence_ref` acts as a fixed release bound (`advanced.py:58-117`).
3. **Config-trusted execution.** `pmi_core/application.py:66` runs `-m <config["scheduling_worker"]>`, and `:35` compares the IFC hash with a hash supplied by the same config. A user-controlled config would allow arbitrary module execution and self-declared model registration.
4. **Static banners.** The R0 viewer's warning and comparison texts are static HTML (Stage 5.4D limitation L3).

## 2. Conditions on the architecture (A1–A6)

| ID | Condition | Why |
|---|---|---|
| **A1** | **Server-side namespace enforcement.** Project-namespace records must be structurally unable to reach the solver: no projection, no relabel to `hypothetical_fixture`, no promotion path. Fixture records must be bound to a registered fixture manifest (model hash plus input snapshot hash), held by the host and not supplied by the request. | Bypass point 1. The runtime's scope check is a label, not an authority. |
| **A2** | **Evidence integrity.** `evidence_ref` must resolve to a stored, content-hashed, immutable evidence object recording uploader, timestamp, model revision, GlobalId(s), tool and version, and units. For element measurements it must include identity evidence showing the full GlobalId. B1 intake: 10 of 11 elements lacked this, and QV18 was probably the wrong element. Recorded pass events need the same, plus scope and authority. | Bypass point 2 and the B1 findings. |
| **A3** | **Approval binding and invalidation.** An authorization record must bind to `(approval_id, input revision hash, scope, model revision hash, register version)`. Any change to the bound input, scope, model revision or register must revert dependent authorizations to PENDING automatically. "Material edit" must be defined; the default is any change. Approvals depending on AP-TOL stay ineffective while AP-TOL is unset. The 88-row register must remain a controlled, versioned artifact that the input service cannot edit. | The proposal says changes "should require a fresh applicability check". This must be a mandatory invalidation. |
| **A4** | **Input versioning and reproducibility.** Use an append-only revision history per record (who, when, previous value, reason). Each scheduling run must take a frozen input snapshot whose hash enters `pipeline_evidence.json`; today `stage_payload_sha256` covers stage outputs but no user-input record. Pin solver determinism for acceptance. The optimizer uses 8 search workers when there are 40 or more tasks (`optimization/engine.py:48`), so timestamps can vary between runs. Either fix workers and seed for controlled runs, or accept on proof values (status, makespan, bound) only. This repeats the earlier RD01 lesson. | Reproducibility requirement; larger synthetic fixtures will cross the 40-task threshold. |
| **A5** | **Host-controlled pipeline configuration.** The pipeline config (worker module, IFC path and hash, estimation config, references) must come from a host allow-list of registered fixtures, never from a user or frontend. The worker must be selected from a fixed mapping. | Bypass point 3. |
| **A6** | **Explicit unit and time-basis semantics.** Every duration-like input must declare its basis (elapsed or working time) and its conversion chain. Example: UI17 is days in the catalogue, hours in B6/template, and minutes in the runtime, and the 5.4A adapter changes the inspection from an elapsed hold to inspector working time. Record the entered value, the normalized value, the conversion rule and the rule version. | The field-mapping finding on UI17 (see CSV) and the UI12 hours stage. |

## 3. Missing requirements (Priority 2, detailed)

**Model revision tracking**
- Bind every IFC-scoped record to the source SHA-256 **and** the canonical `model_version_id`.
- On a new revision, re-resolve GlobalIds and classify each record as *unchanged geometry*, *changed geometry* or *missing element*. Measurements and approvals on changed or missing elements become invalid (A3).
- Duplicate or near-duplicate GlobalIds must be detected and refused. The B1 intake found QV21 and QV29 differing only in the last character.
- The IFC schema and unit scale must be recorded, since the B1 models mix mm and m.

**Evidence integrity**
- Requirements are in A2.
- Also store a reviewer's evidence-verification result separately from authorization. Verifying evidence is not approving it.

**Input versioning**
- Requirements are in A4.
- In addition, the B6 `Binding_template` columns (`input_id_or_path, record_key, contract_field_id, value_json, unit, input_state, evidence_ref, approval_id`) should become the record key, and `approval_id` must never imply approval.

**Approval invalidation**
- Requirements are in A3.
- In addition, B8 and the decision log reference the register by count (75 vs 88). The service should reference a register **version hash**, not a count.

**Reproducibility**
- Requirements are in A4.
- In addition, catalogue reference files (`stage5_3_reference_selection.csv`, BC3 hashes) and the construction library hashes must be captured per run. `build_construction` already records `library_hashes`, so extend the same pattern.

## 4. Items the proposal should correct

1. **"Its consumer column distinguishes supported R0 analogues from future routes."** It does not do so explicitly: no row states implementation status.
   - Several "upstream" destinations exist only in `controlled_demo_input_template.json`, with no code consumer: `construction_method.per_element_group[]`, `reinforcement_mass_kg[]`, `measurement_rules.column_height`, `sequence_choice.inspection_hold_hours_before_pour`, `formwork.slab_on_grade_global_ids` and `zones[]`.
   - The real consumer is the R0-only `5.3A-fixture` config keyed by GlobalId.
   - Status per row is in `field_mapping_verification.csv`: 9 proposed (including UI16's reporting-only analogue), 3 blocker-label-only, 1 implemented but not wired, and 9 fixture-specific (3) or mixed with generic CP-SAT support (6). None has a generic end-to-end consumer today.
2. **UI19:** "applicable lift approval" is not in the 88-row register. This is a register gap to raise for qualified review; this review does not create it.
3. **UI08:** `SupplySource.product` is upstream per the contract. CP-SAT consumes only supply rate, calendar and capacity.
4. **UI12/UI13:** the curing/striking combination has no approval ID (B8 proposal 7). The 5.4A re-anchoring is a controlled interpretation and must not be presented as a rule.
5. **Link check:** all 8 relative links in the proposal resolve.

## 5. Preservation

Verified unchanged:
- the approval register (`d86a26ce…`) and addendum (`fdc1e1ce…`);
- the UI catalogue (`40eb11de…`) and the resource handover CSVs;
- the R0 fixture config (`deaebe52…`);
- the Stage 5.4D `server.py` (`68474798…`);
- Nandini's 8 workbooks (hashes identical to the intake inventory).

This review wrote only into `research/validation/engineering_resource_input_independent/`. The non-R0 probe described in the I04 analysis wrote only to the session scratchpad. Nothing was committed.
