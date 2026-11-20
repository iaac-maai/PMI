# Architecture and module map

| Component | Responsibility |
| --- | --- |
| pmi_core.application | Public pipeline configuration, runtime probes, subprocess isolation, stage evidence hashes, and validated schedule export |
| pmi_core.cli and pmi_core.bim | IFC extraction and canonical BIM input |
| pmi_core.construction | Work packages, activity identities and dependency graphs |
| pmi_core.estimation | Engineering durations, material quantities and direct reference cost |
| pmi_core.scheduling | Existing calendar expansion and CPM baseline |
| pmi_core.optimization.schemas and input_states | Normalized input primitives and provenance audit |
| pmi_core.optimization.registry | Explicit trusted controlled approval records and exception-policy injection |
| pmi_core.optimization.preparation and capacity_dates | Calendar intersections, dated profiles, domains, precedence and lower-bound preparation |
| pmi_core.optimization.model and advanced | CP-SAT intervals, shared capacity, reservations, supply limits, splits and release rules |
| pmi_core.optimization.engine | Primary solve, deadline and horizon probes, earlier-start secondary solve, proof statistics |
| pmi_core.optimization.validation | Timestamp, resource occupancy, release and supply checks |
| pmi_core.optimization.diagnostics | Static contradiction witnesses and schedule-feasibility diagnostics |
| pmi_core.optimization.results and supply_reporting | Versioned result assembly and planning allowances |
| pmi_core.schedule_result | Unified application schedule and stable-ID joins |
| research/implementation/stage5_4b | Controlled fixture and registry adapters, compatibility wrappers and original CLI |
| research/implementation/stage5_4b_integration | R0 application worker, pipeline configuration, tests and integration evidence |

The model uses the existing scheduling calendar utilities. The timestamp validator shares preparation, date profiles and event normalization with the model. It checks serialized results without solver variables. Agent 2's source-fixture oracle provides independent acceptance evidence.

The production optimizer imports no research modules. The registry gate checks 88 unique pending approval records, rejects inconsistent request metadata, and defaults to denying fixture and calendar exceptions. The research adapter supplies the registered exceptions and authority checks. The registry is application configuration, never constructed from normalized request JSON.

The R0 pipeline runs the IFC and estimation stages in the IFC interpreter and CPM and CP-SAT in the planning interpreter. The JSON handover is the process boundary. Its identifier, hash, contract version and interpreter identity are recorded. The orchestration process needs neither IfcOpenShell nor OR-Tools loaded.
