from __future__ import annotations

from pathlib import Path
from typing import Any

from .material_scaffold import formulation_key
from .materials import calculate_formulation_row, nonblank, numeric_value
from .sheets import update_workbook_rows_by_key


NORMALIZED_FORMULATION_FIELDS = ("mass_g", "volume_mL", "moles_mmol", "wt_percent")


def build_formulation_normalization_report(
    tables: dict[str, list[dict[str, Any]]],
    experiment_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    selected_ids = {str(experiment_id).strip() for experiment_id in experiment_ids if str(experiment_id).strip()}
    reagent_lookup = {
        str(row.get("reagent_id", "")).strip(): row
        for row in tables.get("Master Reagents", [])
        if isinstance(row, dict) and str(row.get("reagent_id", "")).strip()
    }
    row_contexts = []
    for row_number, row in enumerate(tables.get("Formulations", []), start=2):
        if not isinstance(row, dict):
            continue
        experiment_id = str(row.get("experiment_id", "")).strip()
        if selected_ids and experiment_id not in selected_ids:
            continue
        enriched_row = enrich_formulation_with_reagent(row, reagent_lookup)
        calculation = calculate_formulation_row(enriched_row)
        row_contexts.append(
            {
                "row_number": row_number,
                "row": row,
                "experiment_id": experiment_id,
                "calculation": calculation,
            }
        )

    mass_totals = formulation_mass_totals(row_contexts)
    for context in row_contexts:
        total_mass = mass_totals.get(context["experiment_id"])
        mass_g = calculation_mass_g(context["calculation"])
        if total_mass is not None and mass_g is not None:
            context["calculation"]["formulation_mass_total_g"] = round(total_mass, 6)
            context["calculation"].setdefault("derived", {}).setdefault(
                "wt_percent",
                round((mass_g / total_mass) * 100, 6),
            )

    runs = []
    seen_updates: set[tuple[str, str, str, str]] = set()
    for context in row_contexts:
        row_number = context["row_number"]
        row = context["row"]
        experiment_id = context["experiment_id"]
        calculation = context["calculation"]
        updates = []
        skipped = []
        for field in NORMALIZED_FORMULATION_FIELDS:
            if nonblank(row.get(field)):
                continue
            if field not in calculation.get("derived", {}):
                skipped.append(
                    {
                        "field": field,
                        "skip_reason": "insufficient_inputs",
                    }
                )
                continue
            update = formulation_update(row, row_number, field, calculation["derived"][field])
            update_key = (*formulation_key(row), field)
            if update_key in seen_updates:
                skipped.append(
                    {
                        "field": field,
                        "skip_reason": "duplicate_update_key",
                    }
                )
                continue
            updates.append(update)
            seen_updates.add(update_key)
        runs.append(
            {
                "experiment_id": experiment_id,
                "formulation_row_number": row_number,
                "reagent_id": row.get("reagent_id", ""),
                "target_role": row.get("target_role", ""),
                "status": "ready" if updates else "skipped",
                "calculation": calculation,
                "update_formulations": updates,
                "skipped_fields": skipped,
            }
        )

    return {
        "schema": "lab-notebook-agent-formulation-normalization.v1",
        "selection": {
            "requested_experiment_ids": list(experiment_ids),
        },
        "summary": summarize_runs(runs),
        "runs": runs,
    }


def apply_formulation_normalization_report_to_workbook(
    workbook_path: str | Path,
    report: dict[str, Any],
    output_workbook: str | Path | None = None,
) -> Path:
    destination = Path(output_workbook).expanduser().resolve() if output_workbook else Path(workbook_path).expanduser().resolve()
    current = Path(workbook_path).expanduser().resolve()
    for run in report.get("runs", []):
        updates = run.get("update_formulations", [])
        if updates:
            update_workbook_rows_by_key(current, "Formulations", updates, destination)
            current = destination
    return destination


def enrich_formulation_with_reagent(
    row: dict[str, Any],
    reagent_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    enriched = dict(row)
    reagent = reagent_lookup.get(str(row.get("reagent_id", "")).strip())
    if reagent:
        enriched["reagent"] = reagent
        for field in ("molecular_weight_g_mol", "density_g_mL", "purity_fraction"):
            enriched.setdefault(f"reagent_{field}", reagent.get(field, ""))
    return enriched


def formulation_mass_totals(row_contexts: list[dict[str, Any]]) -> dict[str, float]:
    mass_values_by_experiment: dict[str, list[float]] = {}
    for context in row_contexts:
        mass_g = calculation_mass_g(context.get("calculation", {}))
        if mass_g is None or mass_g <= 0:
            continue
        mass_values_by_experiment.setdefault(str(context.get("experiment_id", "")), []).append(mass_g)
    return {
        experiment_id: sum(values)
        for experiment_id, values in mass_values_by_experiment.items()
        if len(values) >= 2 and sum(values) > 0
    }


def calculation_mass_g(calculation: dict[str, Any]) -> float | None:
    observed = calculation.get("observed", {}) if isinstance(calculation.get("observed"), dict) else {}
    derived = calculation.get("derived", {}) if isinstance(calculation.get("derived"), dict) else {}
    return numeric_value(observed.get("mass_g")) or numeric_value(derived.get("mass_g"))


def formulation_update(row: dict[str, Any], row_number: int, field: str, value: Any) -> dict[str, Any]:
    experiment_id = str(row.get("experiment_id", "")).strip()
    reagent_id = str(row.get("reagent_id", "")).strip()
    target_role = str(row.get("target_role", "")).strip()
    return {
        "sheet": "Formulations",
        "row_number": row_number,
        "experiment_id": experiment_id,
        "reagent_id": reagent_id,
        "target_role": target_role,
        "key_field": "experiment_id",
        "key_value": experiment_id,
        "field": field,
        "value": format_derived_value(value),
        "reason": "Derived from existing formulation quantity and Master Reagents properties.",
    }


def format_derived_value(value: Any) -> str:
    if isinstance(value, (int, float)):
        text = f"{float(value):.6f}".rstrip("0").rstrip(".")
        return text or "0"
    return str(value)


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "formulation_rows_considered": len(runs),
        "ready": sum(1 for run in runs if run.get("status") == "ready"),
        "skipped": sum(1 for run in runs if run.get("status") == "skipped"),
        "formulation_cells_to_update": sum(len(run.get("update_formulations", [])) for run in runs),
        "fields_skipped": sum(len(run.get("skipped_fields", [])) for run in runs),
    }
