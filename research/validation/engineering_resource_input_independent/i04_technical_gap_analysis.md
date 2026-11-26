# I04 — Independent Technical Gap Analysis

**Reviewer:** Agent 2 (independent verifier) · **Date:** 2026-11-26 · **HEAD:** `5b491e834fbcab5e4bc87e6816a6e7e667423bfa`

**I04, as originally recorded** (Stage 5.4B.3 acceptance report §117, carried as L6 in 5.4C and 5.4D): "the registered R0 worker is research-based and fixture-gated." This analysis traces the whole application path and separates **technical generalization blockers** from **engineering data and approval blockers**.

**Method:**
- read-only code trace with line references;
- the accepted test base (Stage 5.4B acceptance matrix: 30 small CP-SAT reference cases, 28 of them non-R0, plus DEMO-H1);
- an empirical probe that ran the generic front half of the pipeline on a non-R0 IFC (`models/test_case/original.ifc`), with output to the session scratchpad only.

---

## 1. End-to-end trace

`pmi_core.application.run_controlled_pipeline` → IFC + construction (IFC runtime) → estimation (IFC runtime) → scheduling worker (planning runtime) → optional IFC4D export → Stage 5.4D viewer.

| # | Stage | Module | Generic? | R0 / fixture gates (file:line) |
|---|---|---|---|---|
| 0 | Pipeline config | `pmi_core/application.py` | Mostly | `:31` accepts only `pmi-pipeline-config/1` and tick ∈ {5,15}. `:35` checks the IFC hash against a hash **supplied by the same config**, so the check is self-declared. `:66` runs `-m config["scheduling_worker"]`, so the worker is chosen by config. `:71-74` contract and model-identity checks are generic. |
| 1 | IFC ingestion | `pmi_core/adapters/ifc.py`, `bim/*`, `validation/*` | **Yes** | IFC2X3 and IFC4 supported. Probe: a 97-element non-R0 model imported as valid. |
| 2 | Construction packages (5.2) | `pmi_core/cli.py` → `construction/engine.build_construction` | **Yes** | No model gate. Probe: 2 candidate packages, 10 activities, 0 graph issues, all `schedulable: False` with UI-ID blockers. `build_construction` accepts `sequences`, `slab_on_grade`, `provided_quantities` and `catalogue_choices`, but `cli.py:139` passes none of them. |
| 3 | Estimation (5.3) | `pmi_core/estimation/__main__.py`, `engine.py` | **No** | `__main__.py:143-147` rejects any IFC other than `FIXTURE_SHA` (probe: "Fixture scope only"). `engine.py:186-198` requires contract `5.3A-fixture`, `FIXTURE_SHA` on model and config, `hypothetical_only`, and exactly 75 PENDING approvals. `_fixture_measurements` (`:120-159`) requires exactly the three `FIXTURE_ELEMENTS` GlobalIds and class/volume pairs, and takes quantities from config `bounds_m`, `formwork_m2` and `reinforcement_kg`. `:205` allows one element per package. `:210` requires five Stage 5.2 activities. `:225` restricts the sequence enum by family. `:259` requires concrete spec exactly `HA-25/P/20/XC2`. `_external_resources` (`:162-180`) treats CRANE only as explicit none. **Generic parts:** `estimate_operation`, `group_packages`, `_calendar`. |
| 4 | Scheduling handover → 5.4A adapter | `research/implementation/stage5_4b_integration/r0_worker.py:20` → `research/implementation/stage5_4b/fixtures.frozen_r0` (`:134-198`) → `pmi_core/scheduling/fixture.py` | **No** | The worker lives in `research/`. `frozen_r0` loads reference case `R0-{tick}` (`:136`) and `stage5_4a/controlled_schedule_inputs.json`, and checks the handover against Agent 2's R0 reference with `verify_reference` (exactly 12 productive activities, `fixture.py:35`). `adapt`: `ROOT_GUIDS` (`:11-15`), `FIXTURE_SHA`, 75 approvals (`:73-79`), the **Paris→Madrid substitution as a hard requirement** (`:84-89`), alias naming, exactly 21 source dependencies (`:145-146`) and exact `CROSS_SUPPORT` (`:167-168`). Strength events must be the three R0 `hypothetical_pass_at_minimum` events (`fixtures.py:148-152`). |
| 5 | CPM | `pmi_core/scheduling/cpm.calculate` | **Yes**, FS-only | `cpm.py:112` accepts FS only. The SS edge that Stage 5.3 creates for a column `overlap` sequence (`construction/dependencies.py:52`, `estimation/engine.py:236`) cannot be scheduled. |
| 6 | CP-SAT | `pmi_core/optimization/*` | **Yes**, within controlled scope | `engine.py:28` and `preparation.py:33` require `scope == "hypothetical_fixture_only"`. `registry.check_metadata` requires 88 PENDING approvals from a host-injected registry. Fixture exceptions are allowed only through registry callbacks. `preparation.py:80` accepts FS with elapsed lag only. `:160` accepts calendar exceptions only as `hypothetical_fixture`, and only when registered (others are ignored). Activity kinds: productive, inspection, elapsed_hold, milestone. Resource kinds: renewable, labour_trade, equipment, inspector, reusable_asset, supply_source. `engine.py:48` uses 8 workers at 40 or more tasks, which is nondeterministic. Already proven on 30 small reference cases (28 of them non-R0 synthetic) plus DEMO-H1 (acceptance matrix AC-G01/G02 PASSED). |
| 7 | Registry | `research/implementation/stage5_4b/controlled_metadata.py` | **No** (research) | `fixture_metadata_allowed` (`:15-43`) recognises only the R0 `FX-R0-*` exceptions or the construction demo. `calendar_exception_reason` (`:46-63`) recognises only RC06. The production `pmi_core/optimization/registry.py` already provides fixture-free defaults (`no_exceptions`, `unregistered_calendar`). |
| 8 | Result contract | `pmi_core/schedule_result.py` | **Yes** | Model-agnostic join. `real_project_eligible: False` is constant. |
| 9 | IFC4D export | `pmi_core/adapters/ifc4d.py` | **No** | `R0_HASH`, `R0_MODEL`, `R0_START` (`:12-15`). Hash allow-lists `_ACCEPTED_REPLAY` and `_ACCEPTED_LIVE` (`:18-26`, used at `:84`, `:323`). Single segment per activity (`:51`). Proof must be OPTIMAL with bound equal to makespan (`:65-70`). IFC4 only (`:126`). Exactly 21 activities, 3 packages, 3 elements and 28 edges, with 7 activities per package (`:136-161`). Fixed R0 label and plan names. |
| 10 | Viewer projection | `pmi_core/viewer_data.py` | **Yes** | Generic `pmi-ifc4d-viewer/1` builder. |
| 11 | Viewer server | `research/implementation/stage5_4d/server.py` | **No** | `ELEMENTS` (`:19`), tick ∈ {5,15} (`:54`), exactly 3 meshes (`:31`), R0 schedule paths, and re-export via the R0-only adapter. |

## 2. The questions asked

**Where R0-specific dispatch occurs:**
- the config field `scheduling_worker` (`r0_config.json` points to `research.implementation.stage5_4b_integration.r0_worker`);
- `frozen_r0(tick)` selecting reference case `R0-{tick}`;
- `ifc4d._export`, which branches between replay and live against R0 hash allow-lists;
- `server.load_workspace(tick|run_dir)`.

**Where frozen R0 inputs are used:**
- `stage5_3/controlled_fixture_inputs.json` (elements, bounds, quantities, holds, crews, calendar);
- `stage5_4a/controlled_schedule_inputs.json` and its preparation directory;
- the reference cases `R0-5` and `R0-15` (resources, project calendar, start);
- the R2 addendum `FX-R0-*` fixture exceptions;
- Agent 2's Stage 5.3A reference calculation and comparison CSV, used by `verify_reference`.

**Where Stage 5.3 measurement ingestion remains fixture-specific:**
- `_fixture_measurements`: three GlobalIds, box bounds, volumes reconciled to authored and geometry quantities;
- formwork and rebar quantities read straight from config per GlobalId;
- the single-element package assumption;
- the fixed concrete specification;
- the crane explicit-none path.

There is no ingestion path for:
- user-provided or independently measured quantity records — although `build_construction(provided_quantities=…)` exists, the estimation stage ignores it;
- group-level BOQs;
- measurement rules (UI22, AP-DC06/07);
- generic geometry-overlap reconciliation.

**Reusable without modification:**
- IFC adapter and BIM extraction;
- `build_construction`, with its API parameters;
- `estimate_operation`, `group_packages` and `_calendar`;
- `cpm.calculate`;
- the whole `pmi_core.optimization` package, including input-state audit, reservations, strength, inspection and release events, supply, split policy and `capacity_by_date`;
- `ControlledRegistry` with host-supplied fixture-free callbacks;
- `schedule_result` and `viewer_data`.

**Components that reject non-fixture inputs:**
- estimation CLI and `estimate_frame`;
- `pmi_core/scheduling/fixture.adapt` and `verify_reference`;
- the research `r0_worker`, `frozen_r0` and `controlled_metadata` callbacks;
- `ifc4d` controlled and export paths;
- the Stage 5.4D server.

**Contracts needing extension or replacement:**

| Contract | Change |
|---|---|
| `5.3A-fixture` estimation config | **Replace** for new fixtures with a per-record input contract keyed by B6 binding fields (`input_id_or_path`, `record_key`, unit, `input_state`, `evidence_ref`, approval IDs) and model revision. The R0 contract must stay frozen. |
| Handover `5.3A` | **Extend.** Add a generic version tag. Remove the dependence on the R0 alias scheme. Carry explicit duration bases (elapsed vs working) and the declared timezone. Carry multi-element package support only if it is specified. |
| 5.4A `adapt` | **Replace** with a generic normalizer. No aliases, no `ROOT_GUIDS`, one declared timezone, explicit inspection basis. SS or other relations must be rejected with a diagnostic, not converted; converting would be a new assumption. |
| Pipeline config | **Replace** self-declared fields with a host-held registry of registered fixtures (worker module allow-list, model hash, input snapshot hash). |
| IFC4D | **Extend** with a registered-fixture manifest instead of hard-coded constants, leaving the R0 constants untouched. Support multi-segment activities and non-OPTIMAL proof labelling. Remove fixed counts. |
| Viewer | `pmi-ifc4d-viewer/1` is reusable. The server needs a registered-fixture loader, data-driven banners (5.4D L3) and an `Intl` timezone label (L4). |

**IFC4D and frontend restrictions that block additional models:** all items in rows 9 and 11 of the table. These are deliberate trust boundaries accepted in 5.4C and 5.4D. They must be **extended by registration**, not relaxed.

## 3. Blocker classification

| Technical generalization blockers (engineering work, can be built and tested now) | Data and approval blockers (cannot be removed by code) |
|---|---|
| T1 Fixture-locked estimation envelope (row 3) | D1 All 88 approvals PENDING; AP-TOL unset |
| T2 Research-based, R0-dispatched worker and registry (rows 4, 7) | D2 B1 quantity validation open: QV09, QV18, QV23 and QV30 unresolved; 10 of 11 elements lack identity evidence; R0 Tier A unstarted |
| T3 R0 5.4A adapter (alias, timezone substitution, fixed counts) | D3 No real design quantities (UI09 bar schedules), crews, calendars or location, equipment, supply |
| T4 FS-only relations versus Stage 5.2 SS option | D4 Measurement rules undecided (AP-DC06, AP-DC07); curing/striking combination has no approval ID; lift methodology has no approval ID |
| T5 Config-trusted worker dispatch and model hash | D5 Real-project eligibility rules not defined (Stage 5.5 not started) |
| T6 No input-record ingestion (provided quantities, measurement evidence) | |
| T7 Hard-coded IFC4D and viewer trust boundary | |
| T8 Solver determinism at 40 or more tasks | |
| T9 No content-hashed evidence or input snapshot provenance (architecture A2, A4) | |

## 4. Can a generalized worker be developed and tested on synthetic fixtures with eligibility false?

**Yes.** The evidence:
- The optimizer core already solves non-R0 synthetic problems under the controlled scope (28 non-R0 small reference cases plus DEMO-H1, all in the accepted acceptance matrix).
- Stages 1–2 already process arbitrary IFC models.
- The blocking code is concentrated in the estimation envelope, the 5.4A adapter, the research worker and registry, and the IFC4D/viewer boundaries.
- All of these can be generalized behind **new** entry points while the R0 path stays byte-for-byte frozen.

Synthetic fixtures (scripted IFC, like `stage5_2/create_frame.py`, plus `hypothetical_fixture` inputs) need no engineering approval, no AP-TOL and no B1 result, because they make no real-world claim.

**Conditions:**
1. The scope and registration controls in architecture conditions A1 and A5.
2. An independent oracle prepared by Agent 2 before acceptance.
3. Real IFC models are used only for rejection (negative) tests and for robustness of stages 1–2. They are never scheduled.
4. All outputs keep `real_project_eligible: false` and all 88 approvals PENDING.

The staged plan is in [`next_stage_recommendation.md`](next_stage_recommendation.md).
