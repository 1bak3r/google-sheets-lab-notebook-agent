from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import sheet_by_name
from .sheets import append_rows_to_workbook, update_workbook_rows_by_key


def load_experiment_record(path: str | Path) -> dict[str, Any]:
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Experiment record must be a JSON object.")
    return data


def build_experiment_record_report(
    record: dict[str, Any],
    tables: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    experiment = experiment_row_from_record(record)
    experiment_id = str(record.get("experiment_id") or experiment.get("experiment_id", "")).strip()
    if not experiment_id:
        raise ValueError("Experiment record must include experiment_id or experiment.experiment_id.")
    experiment["experiment_id"] = experiment_id

    formulation_items = record_list(record, "formulations", "formulation")
    master_reagent_candidates = master_reagent_rows_from_record(record, formulation_items)
    master_reagents, master_reagent_updates, master_reagent_warnings = reconcile_master_reagent_rows(
        master_reagent_candidates,
        tables or {},
    )
    formulations = [
        with_default_experiment_id(project_sheet_row("Formulations", row), experiment_id)
        for row in formulation_items
    ]
    daily_log = [
        daily_log_row_from_record_item(item, experiment_id, record, index)
        for index, item in enumerate(record_list(record, "daily_log", "observations", "observation"), start=1)
    ]
    results = [
        result_row_from_record_item(item, experiment_id, index)
        for index, item in enumerate(record_list(record, "results", "measurements"), start=1)
    ]
    experiment_rows = [project_sheet_row("Experiments", experiment)]
    warnings = missing_required_warnings("Experiments", experiment_rows)
    warnings.extend(missing_required_warnings("Master Reagents", master_reagents))
    warnings.extend(missing_required_warnings("Formulations", formulations))
    warnings.extend(missing_required_warnings("Daily Log", daily_log))
    warnings.extend(missing_required_warnings("Results", results))
    warnings.extend(master_reagent_warnings)

    return {
        "schema": "lab-notebook-agent-experiment-record.v1",
        "experiment_id": experiment_id,
        "append_master_reagents": master_reagents,
        "update_master_reagents": master_reagent_updates,
        "append_experiments": experiment_rows,
        "append_formulations": formulations,
        "append_daily_log": daily_log,
        "append_results": results,
        "warnings": warnings,
        "summary": {
            "master_reagent_rows_to_append": len(master_reagents),
            "master_reagent_cells_to_update": len(master_reagent_updates),
            "experiment_rows_to_append": len(experiment_rows),
            "formulation_rows_to_append": len(formulations),
            "daily_log_rows_to_append": len(daily_log),
            "result_rows_to_append": len(results),
            "warning_count": len(warnings),
        },
    }


def apply_experiment_record_report_to_workbook(
    workbook_path: str | Path,
    report: dict[str, Any],
    output_workbook: str | Path | None = None,
) -> Path:
    destination = Path(output_workbook).expanduser().resolve() if output_workbook else Path(workbook_path).expanduser().resolve()
    current = Path(workbook_path).expanduser().resolve()
    for sheet_name, report_key in (
        ("Master Reagents", "append_master_reagents"),
        ("Experiments", "append_experiments"),
        ("Formulations", "append_formulations"),
        ("Daily Log", "append_daily_log"),
        ("Results", "append_results"),
    ):
        rows = [row for row in report.get(report_key, []) if isinstance(row, dict)]
        if rows:
            append_rows_to_workbook(current, sheet_name, rows, destination)
            current = destination
    master_reagent_updates = [row for row in report.get("update_master_reagents", []) if isinstance(row, dict)]
    if master_reagent_updates:
        update_workbook_rows_by_key(current, "Master Reagents", master_reagent_updates, output_path=destination)
    return destination


def experiment_row_from_record(record: dict[str, Any]) -> dict[str, Any]:
    experiment = record.get("experiment")
    if isinstance(experiment, dict):
        return dict(experiment)
    return {
        header: record.get(header, "")
        for header in sheet_by_name("Experiments").headers
        if header in record
    }


def record_list(record: dict[str, Any], *keys: str) -> list[Any]:
    for key in keys:
        if key not in record:
            continue
        value = record.get(key)
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return value
        return [value]
    return []


def master_reagent_rows_from_record(record: dict[str, Any], formulation_items: list[Any]) -> list[dict[str, Any]]:
    rows = [
        project_sheet_row("Master Reagents", row)
        for row in record_list(record, "master_reagents", "reagents")
        if isinstance(row, dict)
    ]
    for item in formulation_items:
        if isinstance(item, dict):
            row = master_reagent_row_from_formulation_item(item)
            if row:
                rows.append(row)
    return merge_master_reagent_rows(rows)


def master_reagent_row_from_formulation_item(item: dict[str, Any]) -> dict[str, Any] | None:
    reagent = dict(item.get("reagent")) if isinstance(item.get("reagent"), dict) else {}
    if item.get("reagent_id") and not reagent.get("reagent_id"):
        reagent["reagent_id"] = item.get("reagent_id")
    prefixed_fields = {
        "reagent_name": "name",
        "reagent_common_name": "common_name",
        "reagent_category": "category",
        "reagent_role": "role",
        "reagent_molecular_weight_g_mol": "molecular_weight_g_mol",
        "reagent_density_g_mL": "density_g_mL",
        "reagent_purity_fraction": "purity_fraction",
        "reagent_concentration": "concentration",
        "reagent_concentration_units": "concentration_units",
        "reagent_supplier": "supplier",
        "reagent_lot": "lot",
        "reagent_storage_location": "storage_location",
        "reagent_hazards": "hazards",
        "reagent_notes": "notes",
    }
    for source, target in prefixed_fields.items():
        if source in item and item.get(source) not in (None, "") and target not in reagent:
            reagent[target] = item.get(source)
    projected = project_sheet_row("Master Reagents", reagent)
    if not str(projected.get("reagent_id", "")).strip():
        return None
    data_fields = [header for header in sheet_by_name("Master Reagents").headers if header != "reagent_id"]
    if not any(str(projected.get(header, "")).strip() for header in data_fields):
        return None
    return projected


def merge_master_reagent_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order = []
    for row in rows:
        reagent_id = str(row.get("reagent_id", "")).strip()
        if not reagent_id:
            continue
        if reagent_id not in merged:
            merged[reagent_id] = dict(row)
            order.append(reagent_id)
            continue
        for field, value in row.items():
            if str(merged[reagent_id].get(field, "")).strip():
                continue
            if str(value).strip():
                merged[reagent_id][field] = value
    return [merged[reagent_id] for reagent_id in order]


def reconcile_master_reagent_rows(
    rows: list[dict[str, Any]],
    tables: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    existing_by_id = {
        str(row.get("reagent_id", "")).strip(): (row_number, row)
        for row_number, row in enumerate(tables.get("Master Reagents", []), start=2)
        if isinstance(row, dict) and str(row.get("reagent_id", "")).strip()
    }
    append_rows = []
    updates = []
    warnings = []
    for row in rows:
        reagent_id = str(row.get("reagent_id", "")).strip()
        if not reagent_id:
            append_rows.append(row)
            continue
        if reagent_id not in existing_by_id:
            append_rows.append(row)
            continue
        row_number, existing = existing_by_id[reagent_id]
        for field, value in row.items():
            if field == "reagent_id" or not str(value).strip():
                continue
            current = str(existing.get(field, "")).strip()
            proposed = str(value).strip()
            if not current:
                updates.append(
                    {
                        "sheet": "Master Reagents",
                        "row_number": row_number,
                        "reagent_id": reagent_id,
                        "key_field": "reagent_id",
                        "key_value": reagent_id,
                        "field": field,
                        "value": value,
                    }
                )
            elif current != proposed:
                warnings.append(
                    {
                        "code": "master_reagent_field_conflict",
                        "sheet": "Master Reagents",
                        "reagent_id": reagent_id,
                        "field": field,
                        "existing_value": existing.get(field, ""),
                        "proposed_value": value,
                    }
                )
    return append_rows, updates, warnings


def daily_log_row_from_record_item(
    item: Any,
    experiment_id: str,
    record: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    if isinstance(item, dict):
        row = dict(item)
    else:
        row = {"observation": item}
    if "stage" in row and "process_stage" not in row:
        row["process_stage"] = row.get("stage", "")
    row = with_default_experiment_id(project_sheet_row("Daily Log", row), experiment_id)
    if not row.get("timestamp"):
        row["timestamp"] = default_timestamp(record, index)
    return row


def result_row_from_record_item(item: Any, experiment_id: str, index: int) -> dict[str, Any]:
    row = dict(item) if isinstance(item, dict) else {"value": item}
    if "type" in row and "measurement_type" not in row:
        row["measurement_type"] = row.get("type", "")
    if "unit" in row and "units" not in row:
        row["units"] = row.get("unit", "")
    row = with_default_experiment_id(project_sheet_row("Results", row), experiment_id)
    if not row.get("sample_id"):
        row["sample_id"] = f"{experiment_id}-R-{index:03d}"
    if not row.get("quality_flag"):
        row["quality_flag"] = "observed"
    return row


def project_sheet_row(sheet_name: str, row: dict[str, Any]) -> dict[str, Any]:
    headers = sheet_by_name(sheet_name).headers
    return {
        header: normalize_record_cell(row.get(header, ""))
        for header in headers
    }


def with_default_experiment_id(row: dict[str, Any], experiment_id: str) -> dict[str, Any]:
    if not str(row.get("experiment_id", "")).strip():
        row["experiment_id"] = experiment_id
    return row


def default_timestamp(record: dict[str, Any], index: int) -> str:
    for key in ("timestamp", "date"):
        value = record.get(key)
        if value:
            return str(value)
    experiment = record.get("experiment")
    if isinstance(experiment, dict) and experiment.get("date"):
        return str(experiment["date"])
    return f"recorded-{index:03d}"


def normalize_record_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return value


def missing_required_warnings(sheet_name: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    required_fields = [column.name for column in sheet_by_name(sheet_name).columns if column.required]
    warnings = []
    for index, row in enumerate(rows, start=1):
        missing = [field for field in required_fields if not str(row.get(field, "")).strip()]
        if missing:
            warnings.append(
                {
                    "code": "missing_required_fields",
                    "sheet": sheet_name,
                    "row_index": index,
                    "fields": missing,
                }
            )
    return warnings
