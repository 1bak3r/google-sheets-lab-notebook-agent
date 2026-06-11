from __future__ import annotations

from typing import Any

from .agent import agent_config_values, suggestions_for_experiment
from .materials import audit_experiment_materials, nonblank
from .sheets import build_experiment_entry_from_tables


EXPERIMENT_REQUIRED_FIELDS = ("experiment_id", "date", "process_type", "objective", "status")
STAGES = ("planning", "review")


def build_experiment_preflight_report(
    tables: dict[str, list[dict[str, Any]]],
    experiment_id: str,
    stage: str = "planning",
) -> dict[str, Any]:
    stage = normalize_stage(stage)
    try:
        entry = build_experiment_entry_from_tables(tables, experiment_id)
    except ValueError as exc:
        checks = [
            check(
                "experiment_row",
                "fail",
                str(exc),
                actions=["Add an Experiments row with this experiment_id before scaffolding or review."],
            )
        ]
        return report_payload(experiment_id, stage, {}, {}, checks)

    material_audit = audit_experiment_materials(entry)
    checks = [
        experiment_required_fields_check(entry),
        material_roles_check(material_audit),
        formulation_quantities_check(material_audit),
        reagent_properties_check(material_audit),
        reagent_safety_check(entry, safety_review_required(tables)),
        placeholder_reagents_check(entry),
        observations_check(entry, stage),
        results_check(entry, stage),
        literature_evidence_check(entry),
        open_suggestions_check(tables, experiment_id),
    ]
    return report_payload(experiment_id, stage, entry, material_audit, checks)


def normalize_stage(stage: str) -> str:
    normalized = str(stage or "").strip().lower()
    if normalized not in STAGES:
        raise ValueError(f"Preflight stage must be one of {', '.join(STAGES)}.")
    return normalized


def experiment_required_fields_check(entry: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in EXPERIMENT_REQUIRED_FIELDS if not nonblank(entry.get(field))]
    if missing:
        return check(
            "experiment_required_fields",
            "fail",
            "Experiment row is missing required fields.",
            details={"missing_fields": missing},
            actions=[f"Fill Experiments.{field}." for field in missing],
        )
    return check(
        "experiment_required_fields",
        "pass",
        "Experiment row has the required planning fields.",
    )


def material_roles_check(material_audit: dict[str, Any]) -> dict[str, Any]:
    missing = material_audit.get("missing_required_role_groups", [])
    if missing:
        return check(
            "material_roles",
            "fail",
            "Required process material roles are missing.",
            details={"missing_required_role_groups": missing},
            actions=[
                "Run scaffold-materials or add Formulations rows for: " + ", ".join(str(item) for item in missing) + "."
            ],
        )
    return check(
        "material_roles",
        "pass",
        "Required process material roles are present.",
        details={"role_groups": material_audit.get("role_groups", [])},
    )


def formulation_quantities_check(material_audit: dict[str, Any]) -> dict[str, Any]:
    gaps = material_audit.get("quantity_gaps", [])
    if gaps:
        return check(
            "formulation_quantities",
            "fail",
            "One or more formulation rows lacks a quantitative basis.",
            details={"quantity_gaps": gaps},
            actions=[
                "Fill at least one of mass_g, volume_mL, moles_mmol, wt_percent, or concentration for each Formulations row."
            ],
        )
    return check(
        "formulation_quantities",
        "pass",
        "Every formulation row has a quantitative basis.",
    )


def reagent_properties_check(material_audit: dict[str, Any]) -> dict[str, Any]:
    gaps = material_audit.get("reagent_property_gaps", [])
    if gaps:
        return check(
            "reagent_properties",
            "fail",
            "Master Reagents is missing physical-property fields needed for calculations.",
            details={"reagent_property_gaps": gaps},
            actions=[
                "Fill missing Master Reagents fields such as molecular_weight_g_mol, density_g_mL, or concentration."
            ],
        )
    return check(
        "reagent_properties",
        "pass",
        "Master Reagents has the physical-property fields needed for the current roles.",
    )


def reagent_safety_check(entry: dict[str, Any], required: bool = True) -> dict[str, Any]:
    gaps = []
    for row in entry.get("formulation", []) or []:
        if not isinstance(row, dict) or not str(row.get("reagent_id", "")).strip():
            continue
        if reagent_has_safety_notes(row):
            continue
        gaps.append(
            {
                "reagent_id": row.get("reagent_id", ""),
                "target_role": row.get("target_role", ""),
                "missing_fields": ["hazards"],
            }
        )
    if gaps:
        return check(
            "reagent_safety",
            "fail" if required else "warn",
            "Master Reagents is missing hazards/SDS review notes for one or more formulation reagents.",
            details={"reagent_safety_gaps": gaps, "safety_review_required": required},
            actions=["Fill Master Reagents.hazards with SDS-reviewed handling notes before running or accepting the follow-up."],
        )
    return check(
        "reagent_safety",
        "pass",
        "Master Reagents has hazards/SDS review notes for the formulation reagents.",
        details={"safety_review_required": required},
    )


def reagent_has_safety_notes(row: dict[str, Any]) -> bool:
    reagent = row.get("reagent") if isinstance(row.get("reagent"), dict) else {}
    return any(
        nonblank(value)
        for value in (
            row.get("hazards"),
            row.get("reagent_hazards"),
            reagent.get("hazards"),
        )
    )


def safety_review_required(tables: dict[str, list[dict[str, Any]]]) -> bool:
    raw_value = agent_config_values(tables).get("safety_review_required", "true")
    return str(raw_value).strip().lower() not in {"false", "0", "no", "off"}


def placeholder_reagents_check(entry: dict[str, Any]) -> dict[str, Any]:
    placeholders = []
    for row in entry.get("formulation", []) or []:
        if not isinstance(row, dict):
            continue
        reagent = row.get("reagent") if isinstance(row.get("reagent"), dict) else {}
        text = " ".join(
            str(value)
            for value in [
                row.get("reagent_id", ""),
                reagent.get("name", ""),
                reagent.get("common_name", ""),
                reagent.get("notes", ""),
                row.get("notes", ""),
            ]
        ).lower()
        if "todo" in text or "starter placeholder" in text or str(row.get("reagent_id", "")).startswith("AUTO-"):
            placeholders.append(
                {
                    "reagent_id": row.get("reagent_id", ""),
                    "target_role": row.get("target_role", ""),
                    "name": reagent.get("name", ""),
                }
            )
    if placeholders:
        return check(
            "placeholder_reagents",
            "fail",
            "Generated placeholder reagent rows must be replaced before running.",
            details={"placeholder_reagents": placeholders},
            actions=["Replace TODO/AUTO reagent identities with verified Master Reagents rows and SDS-reviewed hazards."],
        )
    return check(
        "placeholder_reagents",
        "pass",
        "No generated placeholder reagents are linked to this formulation.",
    )


def observations_check(entry: dict[str, Any], stage: str) -> dict[str, Any]:
    observations = [row for row in entry.get("observations", []) or [] if isinstance(row, dict)]
    if observations:
        return check(
            "daily_log_observations",
            "pass",
            "Daily Log has observations for this experiment.",
            details={"observation_count": len(observations)},
        )
    status = "fail" if stage == "review" else "warn"
    return check(
        "daily_log_observations",
        status,
        "Daily Log has no observations for this experiment.",
        details={"observation_count": 0},
        actions=["Capture timestamped observations in Daily Log during setup, feed, hold, workup, and testing."],
    )


def results_check(entry: dict[str, Any], stage: str) -> dict[str, Any]:
    results = [row for row in entry.get("results", []) or [] if isinstance(row, dict)]
    if results:
        return check(
            "results_measurements",
            "pass",
            "Results has measurements for this experiment.",
            details={"result_count": len(results)},
        )
    status = "fail" if stage == "review" else "warn"
    return check(
        "results_measurements",
        status,
        "Results has no measurements for this experiment.",
        details={"result_count": 0},
        actions=["Capture normalized measurements in Results before asking for a result-driven next experiment."],
    )


def literature_evidence_check(entry: dict[str, Any]) -> dict[str, Any]:
    evidence = [row for row in entry.get("literature_evidence", []) or [] if isinstance(row, dict)]
    if evidence:
        return check(
            "literature_evidence",
            "pass",
            "Literature Evidence rows are linked to this experiment.",
            details={"evidence_count": len(evidence)},
        )
    return check(
        "literature_evidence",
        "warn",
        "No Literature Evidence rows are linked yet.",
        details={"evidence_count": 0},
        actions=["Run the agent with --litscout-export or --run-litscout to ground suggestions in literature evidence."],
    )


def open_suggestions_check(tables: dict[str, list[dict[str, Any]]], experiment_id: str) -> dict[str, Any]:
    suggestions = suggestions_for_experiment(tables, experiment_id)
    if not suggestions:
        return check(
            "open_suggestions",
            "pass",
            "No open Agent Suggestions currently block a new suggestion run.",
        )
    return check(
        "open_suggestions",
        "warn",
        "Open Agent Suggestions exist for this experiment.",
        details={
            "suggestion_ids": [
                row.get("suggestion_id", "") for row in suggestions if row.get("suggestion_id")
            ]
        },
        actions=["Review open suggestions and set status to rejected or run_complete before rerunning without --force."],
    )


def report_payload(
    experiment_id: str,
    stage: str,
    entry: dict[str, Any],
    material_audit: dict[str, Any],
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    fail_count = sum(1 for row in checks if row.get("status") == "fail")
    warn_count = sum(1 for row in checks if row.get("status") == "warn")
    ready_to_run = fail_count == 0
    ready_for_agent_suggestion = ready_to_run and (
        stage != "review"
        or (
            any(row.get("name") == "daily_log_observations" and row.get("status") == "pass" for row in checks)
            and any(row.get("name") == "results_measurements" and row.get("status") == "pass" for row in checks)
        )
    )
    return {
        "schema": "lab-notebook-agent-experiment-preflight.v1",
        "experiment_id": experiment_id,
        "stage": stage,
        "status": "needs_attention" if fail_count else ("ready_with_warnings" if warn_count else "ready"),
        "ready_to_run": ready_to_run,
        "ready_for_quantitative_suggestion": bool(material_audit.get("ready_for_quantitative_suggestion", False)),
        "ready_for_agent_suggestion": ready_for_agent_suggestion,
        "summary": {
            "check_count": len(checks),
            "pass_count": sum(1 for row in checks if row.get("status") == "pass"),
            "warn_count": warn_count,
            "fail_count": fail_count,
            "action_count": sum(len(row.get("actions", [])) for row in checks),
        },
        "experiment": {
            "date": entry.get("date", ""),
            "project": entry.get("project", ""),
            "process_type": entry.get("process_type", ""),
            "objective": entry.get("objective", ""),
            "status": entry.get("status", ""),
        },
        "checks": checks,
        "next_actions": collect_actions(checks),
        "material_audit": material_audit,
    }


def check(
    name: str,
    status: str,
    message: str,
    details: dict[str, Any] | None = None,
    actions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "message": message,
        "details": details or {},
        "actions": actions or [],
    }


def collect_actions(checks: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for row in checks:
        for action in row.get("actions", []):
            if action and action not in actions:
                actions.append(str(action))
    if not actions:
        actions.append("Experiment notebook row is ready for the selected preflight stage.")
    return actions
