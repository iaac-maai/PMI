# Teammate B (Nandini) Handover — Intake Review

**Reviewer:** Agent 2 (independent verifier)  
**Date:** 2026-11-26  
**Repository:** HEAD `d05e284`. The handover folder is untracked; it was not moved, renamed or edited.  
**Hashed inventory:** `received_inventory.json` (55 files, SHA-256)

## Summary

The handover is careful and honest:
- Every measured row is self-labelled "needs second review / cannot PASS".
- No approval decision is pre-filled.
- Hypothetical values are segregated from real ones.
- The B6 crosswalk reproduces the repository contract exactly.

**Nothing in this handover is validated, and nothing is an engineering approval.** All 88 approvals remain PENDING, real-project eligibility remains false, and AP-TOL remains unset.

Of the four previously flagged B1 issues, **none is closed**:

| Issue | Status |
|---|---|
| QV09 | Discrepancy reproduced and better localised |
| QV18 | Identity mismatch confirmed, and now more serious (likely the wrong element) |
| QV23 | Element identity evidence still missing |
| QV30 | Element identity evidence still missing |

---

## 1. Location note

The requested path `research/validation/teammate_b_handover/` **does not exist**. The material is in `research/teammateB_handover/`, which is untracked. I reviewed it in place. Where it should live permanently is a team decision. The B1 Read_me itself says evidence should stay outside the repository "until the team agrees how".

## 2. Inventory: what was received

| Group | Files |
|---|---|
| `workbooks/` (8) | <ul><li>`B1_quantity_validation_worksheet.xlsx` (11 rows; Polygon_vertices; Screenshot_checklist)</li><li>`B4_Formwork_Rules.xlsx`</li><li>`B5_Reinforcement_BOQ.xlsx`</li><li>`B6_Resource_Crosswalk.xlsx`</li><li>`B6_Resource_Inputs.xlsx`</li><li>`B7_Baseline_Gantt_HYPOTHETICAL.xlsx` (v1, superseded)</li><li>`B7_Baseline_Gantt_v2_HYPOTHETICAL.xlsx`</li><li>`B8_Review_Register.xlsx`</li></ul> |
| `review/` (2) | <ul><li>`Teammate_B_Decision_Log.xlsx` (36 items)</li><li>`desktop.ini` (Windows metadata; not evidence; should be excluded)</li></ul> |
| `evidence/` (45 images, 11 check IDs) | <ul><li>QV01: 9</li><li>QV09: 3</li><li>QV18: 8</li><li>QV21: 3</li><li>QV22: 3</li><li>QV23: 3</li><li>QV27: 4</li><li>QV28: 3</li><li>QV29: 3</li><li>QV30: 3</li><li>QV32: 3</li></ul> |

The R0 frame (Tier A) was not measured; decision-log items B1-R0-COL, B1-R0-BEAM and B1-R0-SLAB are still pending.

### Not received

These were required by `measurement_instructions.md`:

| Item | Status |
|---|---|
| `QVxx_note.txt` (tool, version, units, file) | None received. The information is partly in worksheet column M. |
| `QV09_vertices.csv`, `QV18_vertices.csv` | Not received. The Polygon_vertices sheet contains vertices **constructed** from edge lengths with assumed right angles, not measured coordinates. |
| Selection or Properties screenshot showing the full GlobalId | Present **only for QV01**. Missing for the other 10. |
| Revit schedule-row screenshots (GUID filter → 1 row, volume) | Not saved for any of QV21–QV32 (stated in her notes). |

## 3. Independent checks performed

I opened all three source IFCs read-only with IfcOpenShell 0.9.0.

| Check | Result |
|---|---|
| All 11 GlobalIds exist with the stated STEP ID, storey and name | ✔ 11/11 |
| Reference volume (worksheet grey column) equals the repository subset and the IFC body mesh volume | ✔ 11/11 |
| IFC class | QV29, QV30 and QV32 are `IfcWallStandardCase`; the worksheet and the repository subset both say `IfcWall`. This is a cosmetic subtype label inherited from upstream. |
| Evidence files listed in the worksheet exist on disk | ✔ 11/11. QV01 has 3 extra files not listed, including an unnamed `1795296792493_image.png`. |
| Rotation hypotheses (QV18, QV21, QV27 bbox vs measured) | **Confirmed.** Plan rotations are −2.928° and 177.072°. A rotated 0.5 × 0.5 L gives bbox 0.525 × 0.510 m. |
| B8 `All_75` vs `priority_approval_register.csv` (`d86a26ce…`) | ✔ Same 75 IDs, all PENDING, zero decision cells filled |
| B6 `UI_crosswalk` vs `required_user_inputs.csv` and `required_user_inputs_mapping.csv` | ✔ 22/22 UI IDs; label, unit, target, scope and rule text identical (0 differences) |
| B6 `Contract_groups` vs `resource_contract_fields.csv` | ✔ All 24 contract objects; field and mandatory counts identical |
| B6 `Binding_template` | ✔ All 22 inputs `missing`; `engineer_approved` deliberately not offered |
| 88 pending approvals | ✔ 75 register items plus 13 AP-X items. The AP-X IDs are listed in §6. |

## 4. Previously identified B1 issues

### QV09 — IfcFooting `CONC-FD01-01` (`05hYJfrx99v$KeaCnnTUNB`, #1076898): **OPEN, discrepancy reproduced**

| Item | Value |
|---|---|
| IFC body | A plain rectangle 0.5 × 4.71 m, extruded 0.3 m, giving 0.7065 m³ |
| Openings | None (`HasOpenings` is empty) |
| Duplicate GUID prefix | The truncated prefix `05hYJfrx99v$KeaC` is **unique** in the file |
| Nandini's measurements | 4.591 × 0.500 × 0.300 m, giving 0.68865 m³ (−2.5%). Revit's own schedule volume is 0.709 m³. |

My finding:
- Revit's 0.709 m³ belongs to this element, and it implies the full extent of about 4.71 m.
- In `QV09_length_4591mm.png`, the measure line's start marker sits visibly inboard of the near end corner.
- The "slots" on the top face are consistent with the many embedded steel `STL-00-PLT` plates located on top of this footing. They are not voids in the footing.

**Most likely explanation: the 4.591 m reading's start endpoint snapped to an intermediate edge, not the end face.** This is a hypothesis, not a resolution.

**Needs from Nandini:**
- Re-measure the long edge end-face to end-face, in plan or elevation view.
- Provide a full-GUID Properties screenshot.
- Measure the opposite long edge and both end edges, since only 3 edges were measured.
- Provide a measured-vertex CSV.

### QV18 — IfcColumn `L形柱:GBZ1d-500X500:667621` (`0CQnC65I52bQtPZXPSNgQt`, #551041, F06-13.900): **OPEN, identity likely wrong**

| Item | Value |
|---|---|
| IFC profile | L shape, 500 × 500 outer, 200 mm legs: 0.16 m² × 2.8 m = 0.448 m³. Her edge lengths and volume agree. |
| Revit status bar of the isolated column | `L形柱:GBZ11b-500X500 1469` |
| What the IFC says about that name | `GBZ11b-500X500` is a **different type**, with 8 instances, all on storeys F01 and F02 (e.g. `3hJfDDzBrBbwUsGRrT9IaJ`). QV18 is `GBZ1d-500X500` on F06, one of 14 instances. |

Both types share the same 500 × 500 L section and 2.8 m height, so matching dimensions cannot prove identity.

**The measured element is probably a GBZ11b column, not QV18.** The Revit schedule GUID filter shows one row with 0.448 m³, but it doesn't establish that the *isolated* element was that row.

**Needs from Nandini:**
- Isolate by the filtered schedule row.
- Capture a Properties screenshot showing IfcGUID `0CQnC65I52bQtPZXPSNgQt` and level F06.
- Re-measure.
- Measure at least one interior angle, or the vertex coordinates.
- State the height basis (AP-DC07).

### QV23 — IfcBeam LL7-200X500 (`0CQnC65I52bQtPZXPSNhtV`, #957223): **OPEN, identity evidence missing**

| Item | Value |
|---|---|
| Dimensions | 1500.3 × 500 × 200 mm, consistent with the IFC (extrusion 1500.286 mm, 0.150029 m³) |
| Screenshots | Show only the dimension. There is no type name, GUID, status bar or schedule row; the status bar reads "Click to enter line start point". |
| Width screenshot | Label partly cropped |

The AP-DC06 statement (does the beam depth include the slab?) has not been given.

**Needs from Nandini:**
- A full-GUID Properties or schedule-row screenshot of the measured element.
- The AP-DC06 note.

### QV30 — IfcWallStandardCase Q1-200mm (`0CQnC65I52bQtPZXPSNha3`, #622980): **OPEN, identity evidence missing**

| Item | Value |
|---|---|
| Dimensions | 1000 × 2800 × 200 mm, consistent with the IFC (0.56 m³) |
| Screenshots | No identity information |
| Type name | Q1-200mm is a common wall type, so the type name alone would not suffice |

**Needs from Nandini:** a full-GUID Properties or schedule-row screenshot.

### Other rows (QV01, QV21, QV22, QV27, QV28, QV29, QV32)

**Dimensions are consistent with the IFC** for all seven.

**QV01** has the strongest identity evidence: a GUID-match screenshot.

The other six identify the element only by type name in the status bar, plus an unsaved schedule filter:
- **QV29 and QV32** share type Q1-250mm, so the type name does not distinguish them.
- **QV21:** the Revit element ID (1897738) differs from the IFC Tag (835065). Revit renumbers elements on import, so this is expected, but it is not proof of identity.

All seven need a full-GUID screenshot before second review can complete.

## 5. Independent cross-check vs engineering approval

| Category | What it is | Status in this handover |
|---|---|---|
| **Independent quantity cross-check** | Dimensions measured by a person, compared with PMI's IFC-derived quantity | Revit Measure on **Revit-imported IFC geometry** measures the same exported mesh. It checks PMI's extraction and arithmetic, not ground truth. It is a *Revit reference cross-check*. Nandini labels it correctly. Revit schedule volumes are a secondary check only. |
| **Validation PASS** | Cross-check within an approved tolerance, with complete evidence | **Impossible now.** AP-TOL is unset, and identity evidence is incomplete for 10 of 11 rows. |
| **Engineering approval** | A qualified engineer's decision on a rule or value (AP-*) | **None present.** B8 has empty decision columns. B4, B5 and B6 values are HYPOTHETICAL (Agent 2 fixture) or MISSING. |

My verification of her files is **software and evidence verification. It is not an approval.** Nothing in this review sets AP-TOL, chooses a measurement rule (AP-DC06 or AP-DC07) or changes any approval status.

## 6. Internal inconsistencies in the handover

1. **Decision log B1-QV09 is stale.** It says "independent measurement not yet taken", while the worksheet holds the 21-Nov measurement and discrepancy.
2. **B1 Read_me A11** still says "nothing here has been measured yet".
3. **All 10 measured B1-QV rows in the decision log** keep the source text "independent measurement not yet taken", which contradicts their own "Revit measured …" value column.
4. **B8 covers 75 approvals, while B6 and the runtime use 88.** The 13 missing AP-X items are:
   - AP-X-CAL-01, AP-X-CAL-02
   - AP-X-CREW-01
   - AP-X-FW-01 to AP-X-FW-04
   - AP-X-INSP-01
   - AP-X-SEQ-01
   - AP-X-SPL-01
   - AP-X-STR-01, AP-X-STR-02
   - AP-X-SUP-01

   B8's `Proposed_addendum` items 1–5 and 8 overlap these. Decision-log item B8-03 already asks for this list; it is provided above.
5. **Evidence naming** doesn't follow the `QVxx_selection.png` / `QVxx_dim_*.png` convention. This is acceptable if the mapping in column Y is kept.
6. **The worksheet's `Depth`/`Length` columns are used inconsistently** for polygon rows. For QV09, P = 4.591 (length) and Q = 0.3 (extrusion). Volumes are still right because R × Q is used.
7. **B6-07:** the 1 March 2027 holiday claim is sourced from a ChatGPT thread and is unverified. It must not be used as a real calendar input. As B6-09 notes, it is a test override only.
8. **Privacy:** the screenshots include a personal Revit account name and taskbar or notification content. Crop them before any external sharing.

## 7. What can be reviewed now

- **B6 crosswalk and Binding_template:** accurate against the repository contract. It is suitable as the UI-to-contract reference for B6. No production resource input is created or changed by it.
- **B4 and B5 templates:** their structure and the repository-sourced BCCA values are consistent with the Stage 5.3 selection. All engineering cells are correctly blank or hypothetical.
- **B8:** suitable as the meeting package once the 13 AP-X rows are merged in.
- **B1 rows QV01, QV21, QV22, QV27, QV28, QV29, QV32:** dimensions can be second-reviewed as *Revit reference cross-checks*. They are not PASS.
- **B7 v2:** remains HYPOTHETICAL and is not comparable with the accepted R0 schedule. It was not re-reviewed here.

## 8. Still requires Nandini's clarification

1. **QV18:** re-identify and re-measure the correct F06 GBZ1d column, with a full-GUID screenshot.
2. **QV09:** re-measure the full long edge end-face to end-face, measure all 4 edges, provide a full-GUID screenshot and a vertex CSV.
3. **QV23 and QV30:** provide identity screenshots; for QV23, also the AP-DC06 depth note.
4. **QV21–QV32:** full-GUID screenshots, or saved schedule-row screenshots.
5. **QV01 and QV18:** measured vertex coordinates (not constructed); **QV09:** see item 2.
6. Per-element notes (tool, version, units, file).
7. Update the stale decision-log and Read_me entries (§6, items 1–3).
8. Decide where the evidence folder lives (see §1).
9. **R0 Tier A** (B1-R0-COL, B1-R0-BEAM, B1-R0-SLAB) has not been started.

## 9. Still requires engineering approval (unchanged, all PENDING)

- **AP-TOL:** quantity tolerance, which is the prerequisite for any PASS.
- **AP-DC06:** beam depth basis.
- **AP-DC07:** column height basis.
- **AP-CR06, AP-CR11, AP-CR13:** method, foundation and slab-on-grade classification.
- **AP-W-\*:** BCCA work items and variants.
- **AP-W-CURE, AP-DR07, AP-DR08:** curing and striking criteria.
- **AP-X-\*:** the 13 resource-contract items.
- **Project data:** real reinforcement mass (UI09), crews, calendar, location and timezone, equipment and supply. All are MISSING or HYPOTHETICAL.

## 10. Preservation

This review only read files and wrote into `research/validation/teammate_b_handover_intake/`. Nothing else was changed:
- the accepted scheduling code, R0 fixtures, the Stage 5.4D frontend and production resource inputs;
- approval statuses, the source IFCs and Nandini's files.

Nothing was committed.
