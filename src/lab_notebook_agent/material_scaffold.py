from __future__ import annotations

from pathlib import Path
from typing import Any

from .material_search import (
    master_reagent_records,
    material_role_query,
    ranked_reagent_candidates,
)
from .materials import role_specs_for_process
from .search import LocalSemanticIndex
from .sheets import append_rows_to_workbook


DEFAULT_ROLE_PLANS = {
    "monomer": {
        "target_role": "core_monomer",
        "phase": "monomer feed",
        "feed_order": "1",
        "feed_start_min": "0",
        "feed_duration_min": "180",
        "category": "monomer",
        "name": "TODO monomer or comonomer",
        "common_name": "TODO monomer",
    },
    "initiator": {
        "target_role": "initiator",
        "phase": "initiator feed",
        "feed_order": "2",
        "feed_start_min": "0",
        "feed_duration_min": "210",
        "category": "initiator",
        "name": "TODO initiator",
        "common_name": "TODO initiator",
    },
    "surfactant": {
        "target_role": "surfactant",
        "phase": "aqueous",
        "feed_order": "0",
        "feed_start_min": "",
        "feed_duration_min": "",
        "category": "surfactant",
        "name": "TODO surfactant",
        "common_name": "TODO surfactant",
    },
    "aqueous_phase": {
        "target_role": "solvent",
        "phase": "aqueous",
        "feed_order": "0",
        "feed_start_min": "",
        "feed_duration_min": "",
        "category": "solvent",
        "name": "deionized water",
        "common_name": "DI water",
    },
    "crosslinker_or_chain_transfer": {
        "target_role": "crosslinker",
        "phase": "monomer feed",
        "feed_order": "1",
        "feed_start_min": "0",
        "feed_duration_min": "180",
        "category": "crosslinker",
        "name": "TODO optional crosslinker or chain-transfer agent",
        "common_name": "TODO optional",
    },
}


def build_material_scaffold_report(
    tables: dict[str, list[dict[str, Any]]],
    experiment_id: str,
    process_type: str | None = None,
    include_optional: bool = False,
    query: str = "",
) -> dict[str, Any]:
    process_type = process_type or experiment_process_type(tables, experiment_id)
    role_specs = role_specs_for_process(str(process_type).lower())
    master_reagents = [row for row in tables.get("Master Reagents", []) if isinstance(row, dict)]
    reagent_records = master_reagent_records(master_reagents)
    reagent_index = LocalSemanticIndex(reagent_records) if reagent_records else None
    existing_formulation = [
        row
        for row in tables.get("Formulations", [])
        if isinstance(row, dict) and str(row.get("experiment_id", "")).strip() == experiment_id
    ]
    existing_reagent_ids = {
        str(row.get("reagent_id", "")).strip()
        for row in master_reagents
        if row.get("reagent_id")
    }
    append_master_reagents: list[dict[str, Any]] = []
    append_formulations: list[dict[str, Any]] = []
    role_scaffold = []

    for spec in role_specs:
        if not spec.get("required") and not include_optional and spec["role_group"] != "aqueous_phase":
            continue
        role_group = str(spec["role_group"])
        if formulation_has_role(existing_formulation, spec):
            role_scaffold.append(
                {
                    "role_group": role_group,
                    "status": "already_present",
                    "action": "none",
                }
            )
            continue

        role_plan = DEFAULT_ROLE_PLANS.get(role_group, {})
        candidate = ranked_master_reagent_candidate(
            spec,
            str(process_type),
            query,
            reagent_records,
            reagent_index,
        )
        if candidate:
            reagent_id = str(candidate.get("reagent_id", "")).strip()
            reagent_action = "reuse_existing_master_reagent"
            selection_method = "ranked_process_material_search"
        else:
            reagent_id = placeholder_reagent_id(experiment_id, role_group)
            reagent_action = "append_placeholder_master_reagent"
            selection_method = "placeholder"
            if reagent_id not in existing_reagent_ids:
                append_master_reagents.append(
                    placeholder_master_reagent(
                        reagent_id,
                        role_group,
                        role_plan,
                        process_type=str(process_type),
                    )
                )
                existing_reagent_ids.add(reagent_id)

        formulation_row = starter_formulation_row(
            experiment_id,
            reagent_id,
            role_group,
            role_plan,
        )
        if not formulation_duplicate(formulation_row, existing_formulation + append_formulations):
            append_formulations.append(formulation_row)

        role_entry = {
            "role_group": role_group,
            "status": "missing",
            "action": reagent_action,
            "selection_method": selection_method,
            "reagent_id": reagent_id,
            "target_role": formulation_row["target_role"],
        }
        if candidate:
            role_entry["selected_candidate"] = scaffold_candidate_summary(candidate)
        role_scaffold.append(role_entry)

    return {
        "schema": "lab-notebook-agent-material-scaffold.v1",
        "experiment_id": experiment_id,
        "process_type": process_type,
        "include_optional": include_optional,
        "query": query,
        "role_scaffold": role_scaffold,
        "append_master_reagents": append_master_reagents,
        "append_formulations": append_formulations,
        "summary": {
            "role_groups_considered": len(role_scaffold),
            "master_reagent_rows_to_append": len(append_master_reagents),
            "formulation_rows_to_append": len(append_formulations),
        },
    }


def apply_material_scaffold_report_to_workbook(
    workbook_path: str | Path,
    report: dict[str, Any],
    output_workbook: str | Path | None = None,
) -> Path:
    destination = (
        Path(output_workbook).expanduser().resolve()
        if output_workbook
        else Path(workbook_path).expanduser().resolve()
    )
    current = Path(workbook_path).expanduser().resolve()
    master_rows = report.get("append_master_reagents", [])
    formulation_rows = report.get("append_formulations", [])
    if master_rows:
        append_rows_to_workbook(current, "Master Reagents", master_rows, destination)
        current = destination
    if formulation_rows:
        append_rows_to_workbook(current, "Formulations", formulation_rows, destination)
        current = destination
    return destination


def experiment_process_type(tables: dict[str, list[dict[str, Any]]], experiment_id: str) -> str:
    for row in tables.get("Experiments", []):
        if str(row.get("experiment_id", "")).strip() == experiment_id:
            return str(row.get("process_type", "")).strip()
    return ""


def formulation_has_role(formulation: list[dict[str, Any]], spec: dict[str, Any]) -> bool:
    acceptable = {str(role).lower() for role in spec.get("acceptable_roles", [])}
    for row in formulation:
        target_role = str(row.get("target_role", "")).strip().lower()
        if target_role in acceptable:
            return True
    return False


def ranked_master_reagent_candidate(
    spec: dict[str, Any],
    process_type: str,
    query: str,
    reagent_records: list[dict[str, Any]],
    reagent_index: LocalSemanticIndex | None,
) -> dict[str, Any] | None:
    role_query = material_role_query(process_type, spec, query)
    candidates = ranked_reagent_candidates(
        spec,
        role_query,
        reagent_records,
        reagent_index,
        k=max(1, len(reagent_records)),
    )
    for candidate in candidates:
        if candidate.get("match_reasons") == ["semantic_text_match"]:
            continue
        if str(candidate.get("reagent_id", "")).strip():
            return candidate
    return None


def scaffold_candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "score": candidate.get("score", 0),
        "semantic_score": candidate.get("semantic_score", 0),
        "match_reasons": candidate.get("match_reasons", []),
        "row_number": candidate.get("row_number", ""),
        "reagent_id": candidate.get("reagent_id", ""),
        "name": candidate.get("name", ""),
        "common_name": candidate.get("common_name", ""),
        "category": candidate.get("category", ""),
        "role": candidate.get("role", ""),
        "important_fields_complete": candidate.get("important_fields_complete", True),
        "missing_important_fields": candidate.get("missing_important_fields", []),
    }


def placeholder_reagent_id(experiment_id: str, role_group: str) -> str:
    compact_role = {
        "monomer": "MONOMER",
        "initiator": "INITIATOR",
        "surfactant": "SURFACTANT",
        "aqueous_phase": "WATER",
        "crosslinker_or_chain_transfer": "OPTIONAL",
    }.get(role_group, role_group.upper().replace(" ", "_"))
    return f"AUTO-{experiment_id}-{compact_role}".replace(" ", "-")


def placeholder_master_reagent(
    reagent_id: str,
    role_group: str,
    role_plan: dict[str, str],
    process_type: str,
) -> dict[str, Any]:
    return {
        "reagent_id": reagent_id,
        "name": role_plan.get("name", f"TODO {role_group}"),
        "common_name": role_plan.get("common_name", ""),
        "category": role_plan.get("category", "unknown"),
        "role": f"{role_group} for {process_type}",
        "molecular_weight_g_mol": "",
        "density_g_mL": "",
        "purity_fraction": "",
        "concentration": "",
        "concentration_units": "",
        "supplier": "",
        "lot": "",
        "storage_location": "",
        "hazards": "TODO verify SDS before use",
        "notes": "Starter placeholder generated by lab-notebook-agent; replace with verified reagent identity and physical properties.",
    }


def starter_formulation_row(
    experiment_id: str,
    reagent_id: str,
    role_group: str,
    role_plan: dict[str, str],
) -> dict[str, Any]:
    return {
        "experiment_id": experiment_id,
        "reagent_id": reagent_id,
        "phase": role_plan.get("phase", ""),
        "target_role": role_plan.get("target_role", role_group),
        "mass_g": "",
        "volume_mL": "",
        "moles_mmol": "",
        "concentration": "",
        "concentration_units": "",
        "wt_percent": "",
        "feed_order": role_plan.get("feed_order", ""),
        "feed_start_min": role_plan.get("feed_start_min", ""),
        "feed_duration_min": role_plan.get("feed_duration_min", ""),
        "notes": "Starter row generated by lab-notebook-agent; enter actual quantity before running.",
    }


def formulation_duplicate(row: dict[str, Any], existing_rows: list[dict[str, Any]]) -> bool:
    key = formulation_key(row)
    return any(formulation_key(existing) == key for existing in existing_rows)


def formulation_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("experiment_id", "")).strip(),
        str(row.get("reagent_id", "")).strip(),
        str(row.get("target_role", "")).strip(),
    )
