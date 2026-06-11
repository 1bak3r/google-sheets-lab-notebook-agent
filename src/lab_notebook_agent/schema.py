from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Column:
    name: str
    description: str
    required: bool = False


@dataclass(frozen=True)
class SheetSpec:
    name: str
    columns: tuple[Column, ...]
    example_rows: tuple[tuple[object, ...], ...] = ()

    @property
    def headers(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)


PROCESS_TYPES = (
    "emulsion polymerization",
    "solution polymerization",
    "bulk polymerization",
    "suspension polymerization",
    "latex characterization",
    "compounding",
    "hydrolysis study",
)

REAGENT_CATEGORIES = (
    "monomer",
    "initiator",
    "surfactant",
    "solvent",
    "buffer",
    "chain_transfer_agent",
    "crosslinker",
    "inhibitor",
    "additive",
    "matrix_polymer",
    "unknown",
)

FORMULATION_ROLES = (
    "core_monomer",
    "shell_monomer",
    "comonomer",
    "initiator",
    "surfactant",
    "buffer",
    "chain_transfer_agent",
    "crosslinker",
    "solvent",
    "neutralizer",
    "additive",
)

EXPERIMENT_STATUS = (
    "planned",
    "running",
    "complete",
    "needs_review",
    "abandoned",
)

PROCESS_STAGES = (
    "setup",
    "seed",
    "feed",
    "hold",
    "chase",
    "workup",
    "sampling",
    "test",
    "cleanup",
)

RESULT_QUALITY_FLAGS = (
    "planned",
    "observed",
    "ok",
    "suspect",
    "repeat",
    "failed",
)

SUGGESTION_STATUS = (
    "draft",
    "accepted",
    "rejected",
    "run_planned",
    "run_complete",
)

DAILY_REVIEW_STATUS = (
    "needs_attention",
    "ready_to_apply",
    "ready_with_warnings",
    "no_action",
)

CONTROLLED_VOCAB_VALIDATIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "Master Reagents": {"category": REAGENT_CATEGORIES},
    "Experiments": {"process_type": PROCESS_TYPES, "status": EXPERIMENT_STATUS},
    "Daily Log": {"process_stage": PROCESS_STAGES},
    "Formulations": {"target_role": FORMULATION_ROLES},
    "Results": {"quality_flag": RESULT_QUALITY_FLAGS},
    "Agent Suggestions": {"status": SUGGESTION_STATUS},
    "Daily Reviews": {"status": DAILY_REVIEW_STATUS},
}

SHEETS: tuple[SheetSpec, ...] = (
    SheetSpec(
        name="Master Reagents",
        columns=(
            Column("reagent_id", "Stable short ID used by formulation rows.", True),
            Column("name", "Full reagent name.", True),
            Column("common_name", "Short lab name or abbreviation."),
            Column("category", "Controlled reagent category.", True),
            Column("role", "Typical role in experiments."),
            Column("molecular_weight_g_mol", "Molecular weight in g/mol."),
            Column("density_g_mL", "Density in g/mL when relevant."),
            Column("purity_fraction", "Purity from 0 to 1."),
            Column("concentration", "Stock concentration if this is a solution."),
            Column("concentration_units", "Units for concentration."),
            Column("supplier", "Supplier or source."),
            Column("lot", "Lot or batch identifier."),
            Column("storage_location", "Freezer, cabinet, hood, or shelf."),
            Column("hazards", "Short safety notes."),
            Column("notes", "Additional user notes."),
        ),
        example_rows=(
            (
                "M-SKA",
                "solketal acrylate",
                "SKA",
                "monomer",
                "rubbery acrylic core monomer",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "combustible/irritant; verify SDS",
                "Seed row; replace values with verified inventory data.",
            ),
            (
                "I-APS",
                "ammonium persulfate",
                "APS",
                "initiator",
                "water-soluble radical initiator",
                "228.20",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "oxidizer; verify SDS",
                "Common emulsion polymerization initiator.",
            ),
            (
                "S-SDS",
                "sodium dodecyl sulfate",
                "SDS",
                "surfactant",
                "anionic surfactant",
                "288.38",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "irritant; verify SDS",
                "Example surfactant row.",
            ),
        ),
    ),
    SheetSpec(
        name="Experiments",
        columns=(
            Column("experiment_id", "Stable experiment ID.", True),
            Column("date", "Experiment date as YYYY-MM-DD.", True),
            Column("project", "Project or product line."),
            Column("process_type", "Controlled process type.", True),
            Column("objective", "What the experiment is trying to learn.", True),
            Column("hypothesis", "Expected outcome or mechanism."),
            Column("linked_literature_ids", "Evidence IDs from Literature Evidence."),
            Column("operator", "Person running the experiment."),
            Column("status", "Experiment state.", True),
            Column("planned_next_step", "Human-planned next action."),
            Column("summary", "Short run summary after completion."),
        ),
        example_rows=(
            (
                "EP-001",
                "2026-06-09",
                "SABER CCSP",
                "emulsion polymerization",
                "Reduce particle size while avoiding coagulum.",
                "A slower monomer feed and balanced surfactant package should narrow PSD.",
                "",
                "",
                "planned",
                "",
                "",
            ),
        ),
    ),
    SheetSpec(
        name="Daily Log",
        columns=(
            Column("experiment_id", "Experiment ID linked to Experiments.", True),
            Column("timestamp", "Observation timestamp.", True),
            Column("process_stage", "Setup, seed, feed, hold, workup, test, etc."),
            Column("temperature_C", "Observed reactor/sample temperature."),
            Column("rpm", "Agitation speed."),
            Column("pH", "Measured pH."),
            Column("solids_percent", "Measured or estimated solids percent."),
            Column("particle_size_nm", "Particle size if measured."),
            Column("conversion_percent", "Conversion if measured."),
            Column("viscosity_cP", "Viscosity if measured."),
            Column("observation", "Free-text notebook observation.", True),
            Column("issue_tags", "Comma-separated tags such as coagulum or low_conversion."),
            Column("attachments_url", "Link to photos, spectra, files, or Drive folders."),
            Column("residual_monomer_percent", "Residual monomer if measured."),
            Column("polydispersity_index", "DLS polydispersity index if measured."),
            Column("Tg_C", "Glass transition temperature if measured."),
            Column("hold_time_min", "Thermal or reaction hold time."),
        ),
        example_rows=(
            (
                "EP-001",
                "2026-06-09T14:35:00",
                "feed",
                "70",
                "250",
                "",
                "",
                "420",
                "",
                "",
                "Latex looked bluish but small coagulum appeared on stir shaft.",
                "coagulum,particle_size_high",
                "",
                "",
                "",
                "",
                "",
            ),
        ),
    ),
    SheetSpec(
        name="Formulations",
        columns=(
            Column("experiment_id", "Experiment ID linked to Experiments.", True),
            Column("reagent_id", "Reagent ID from Master Reagents.", True),
            Column("phase", "Aqueous, monomer, seed, initiator, chase, etc."),
            Column("target_role", "Controlled formulation role.", True),
            Column("mass_g", "Mass in grams."),
            Column("volume_mL", "Volume in mL."),
            Column("moles_mmol", "Moles in mmol."),
            Column("concentration", "Concentration value."),
            Column("concentration_units", "Concentration units."),
            Column("wt_percent", "Weight percent in formulation."),
            Column("feed_order", "Order added."),
            Column("feed_start_min", "Feed start time in minutes."),
            Column("feed_duration_min", "Feed duration in minutes."),
            Column("notes", "Formulation notes."),
        ),
        example_rows=(
            ("EP-001", "M-SKA", "monomer feed", "core_monomer", "", "", "", "", "", "", "1", "0", "180", ""),
            ("EP-001", "I-APS", "initiator feed", "initiator", "", "", "", "", "", "", "2", "0", "210", ""),
            ("EP-001", "S-SDS", "aqueous", "surfactant", "", "", "", "", "", "", "0", "", "", ""),
        ),
    ),
    SheetSpec(
        name="Results",
        columns=(
            Column("experiment_id", "Experiment ID linked to Experiments.", True),
            Column("sample_id", "Sample or aliquot ID.", True),
            Column("measurement_type", "DLS, GC, NMR, DSC, tensile, impact, etc.", True),
            Column("method", "Instrument or method details."),
            Column("value", "Numeric or text result."),
            Column("units", "Measurement units."),
            Column("condition", "Temperature, matrix, aging, replicate conditions."),
            Column("replicate", "Replicate number."),
            Column("quality_flag", "ok, suspect, repeat, failed."),
            Column("interpretation", "Human interpretation."),
        ),
        example_rows=(
            ("EP-001", "EP-001-L1", "DLS particle size", "intensity average", "420", "nm", "post-feed", "1", "suspect", "Above target range."),
        ),
    ),
    SheetSpec(
        name="Literature Evidence",
        columns=(
            Column("evidence_id", "Stable evidence row ID.", True),
            Column("source", "LitScout backend, paper, patent, local note, or manual."),
            Column("title", "Source title."),
            Column("authors", "Authors or assignees."),
            Column("year", "Publication year."),
            Column("doi_or_url", "DOI, patent URL, or source URL."),
            Column("query", "Search query that found this evidence."),
            Column("finding", "Short finding relevant to experiments.", True),
            Column("relevance_tags", "Tags such as surfactant, particle_size, initiator."),
            Column("confidence", "low, medium, high."),
            Column("notes", "Additional review notes."),
        ),
    ),
    SheetSpec(
        name="Agent Suggestions",
        columns=(
            Column("suggestion_id", "Stable suggestion ID.", True),
            Column("created_at", "UTC timestamp."),
            Column("experiment_id", "Experiment ID the suggestion responds to.", True),
            Column("recommendation_type", "next_experiment, literature_search, data_cleanup, safety_review."),
            Column("rationale", "Why the agent suggested this."),
            Column("proposed_change", "Concrete change or experiment to run."),
            Column("expected_effect", "Expected measurable effect."),
            Column("linked_evidence_ids", "Literature Evidence IDs used."),
            Column("safety_check", "Safety or review reminder."),
            Column("confidence", "low, medium, high."),
            Column("status", "Controlled suggestion status."),
            Column("proposed_experiment_id", "Suggested follow-up experiment ID if accepted."),
            Column("proposed_plan_json", "Structured proposed experiment plan for review/materialization."),
        ),
    ),
    SheetSpec(
        name="Daily Reviews",
        columns=(
            Column("review_id", "Stable daily review ID.", True),
            Column("created_at", "UTC timestamp for the review row."),
            Column("review_date", "Date reviewed as YYYY-MM-DD.", True),
            Column("selected_experiment_ids", "Comma-separated selected experiment IDs."),
            Column("experiment_count", "Number of experiments reviewed."),
            Column("observation_count", "Daily Log observations counted."),
            Column("result_count", "Existing Results rows counted before appending new rows."),
            Column("normalized_result_rows_to_append", "Pending Results rows from Daily Log normalization."),
            Column("evidence_rows_to_append", "Pending Literature Evidence rows."),
            Column("suggestion_rows_to_append", "Pending Agent Suggestions rows."),
            Column("preflight_fail_count", "Total failed preflight checks."),
            Column("preflight_warn_count", "Total warning preflight checks."),
            Column("apply_request_count", "Google Sheets batchUpdate request count when available."),
            Column("status", "Daily review state."),
            Column("summary", "Short human-readable run summary."),
            Column("next_actions_json", "JSON list of recommended next actions."),
        ),
    ),
    SheetSpec(
        name="Process Knowledge",
        columns=(
            Column("process_type", "Process name.", True),
            Column("material_role", "Role category."),
            Column("typical_examples", "Typical materials for semantic lookup."),
            Column("measured_fields", "Useful measurements to capture."),
            Column("guidance", "Short process guidance."),
            Column("search_terms", "Terms used to generate literature queries."),
        ),
        example_rows=(
            (
                "emulsion polymerization",
                "monomer",
                "acrylate monomers, methacrylate monomers, functional comonomers, crosslinkers",
                "mass_g, moles_mmol, conversion_percent, Tg",
                "Track monomer feed timing, core/shell target, and conversion.",
                "emulsion polymerization acrylic monomer core shell latex conversion",
            ),
            (
                "emulsion polymerization",
                "initiator",
                "ammonium persulfate, potassium persulfate, redox initiator systems",
                "initiator concentration, temperature_C, conversion_percent",
                "Initiator level and temperature affect radical flux, conversion, and nucleation.",
                "emulsion polymerization persulfate initiator radical flux particle nucleation",
            ),
            (
                "emulsion polymerization",
                "surfactant",
                "SDS, nonionic fatty alcohol ethoxylates, mixed ionic/nonionic surfactants",
                "particle_size_nm, solids_percent, coagulum, viscosity_cP",
                "Surfactant package and feed profile often control latex stability and particle size.",
                "emulsion polymerization surfactant particle size coagulum latex stability",
            ),
        ),
    ),
    SheetSpec(
        name="Controlled Vocab",
        columns=(
            Column("field", "Field name."),
            Column("allowed_value", "Allowed value."),
            Column("description", "Meaning."),
        ),
        example_rows=tuple(
            ("process_type", value, "Experiment process type.") for value in PROCESS_TYPES
        )
        + tuple(("reagent_category", value, "Master Reagents category.") for value in REAGENT_CATEGORIES)
        + tuple(("formulation_role", value, "Formulations target role.") for value in FORMULATION_ROLES)
        + tuple(("experiment_status", value, "Experiments status.") for value in EXPERIMENT_STATUS)
        + tuple(("process_stage", value, "Daily Log process stage.") for value in PROCESS_STAGES)
        + tuple(("result_quality_flag", value, "Results quality flag.") for value in RESULT_QUALITY_FLAGS)
        + tuple(("suggestion_status", value, "Agent Suggestions status.") for value in SUGGESTION_STATUS)
        + tuple(("daily_review_status", value, "Daily Reviews status.") for value in DAILY_REVIEW_STATUS),
    ),
    SheetSpec(
        name="Agent Config",
        columns=(
            Column("key", "Configuration key.", True),
            Column("value", "Configuration value."),
            Column("notes", "Usage notes."),
        ),
        example_rows=(
            ("default_context_limit", "5", "Notebook search matches to include per agent run."),
            ("default_history_limit", "5", "Same-process prior experiments to include as result benchmarks."),
            ("default_evidence_limit", "3", "Literature Evidence rows to append or select per experiment."),
            ("default_litscout_sources", "openalex,crossref,semantic_scholar", "Sources used by generated LitScout commands."),
            ("default_litscout_depth", "light", "Increase to medium/intense when a search is promising."),
            ("default_litscout_limit", "8", "LitScout works to retrieve when the agent runs LitScout live."),
            ("suggestion_confidence_floor", "medium", "Human review required before running suggested experiments."),
            ("require_literature_evidence", "false", "Set true to skip suggestions unless Literature Evidence is linked or generated."),
            ("safety_review_required", "true", "Agent suggestions do not replace SDS, SOP, or PI review."),
        ),
    ),
)


def sheet_by_name(name: str) -> SheetSpec:
    for sheet in SHEETS:
        if sheet.name == name:
            return sheet
    raise KeyError(name)


def workbook_contract() -> dict[str, object]:
    return {
        "name": "lab-notebook-agent-workbook",
        "version": "0.1.0",
        "sheets": [
            {
                "name": sheet.name,
                "headers": list(sheet.headers),
                "columns": [
                    {
                        "name": column.name,
                        "description": column.description,
                        "required": column.required,
                    }
                    for column in sheet.columns
                ],
            }
            for sheet in SHEETS
        ],
        "controlled_vocab": {
            "process_type": list(PROCESS_TYPES),
            "reagent_category": list(REAGENT_CATEGORIES),
            "formulation_role": list(FORMULATION_ROLES),
            "experiment_status": list(EXPERIMENT_STATUS),
            "process_stage": list(PROCESS_STAGES),
            "result_quality_flag": list(RESULT_QUALITY_FLAGS),
            "suggestion_status": list(SUGGESTION_STATUS),
            "daily_review_status": list(DAILY_REVIEW_STATUS),
        },
    }
