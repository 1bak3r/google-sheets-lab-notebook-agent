from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agent import suggestion_to_workbook_row
from .material_scaffold import formulation_key
from .planning import result_row_key
from .schema import SHEETS, sheet_by_name
from .sheets import rows_from_values


def load_agent_report(path: str | Path) -> dict[str, Any]:
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Agent report must be a JSON object.")
    return data


def load_sheet_snapshot(path: str | Path) -> dict[str, Any]:
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Google Sheets snapshot must be a JSON object.")
    return data


def snapshot_to_tables(snapshot: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    sheets = snapshot.get("sheets")
    if not isinstance(sheets, dict):
        raise ValueError("Snapshot must include a sheets object.")
    tables: dict[str, list[dict[str, Any]]] = {}
    for sheet_name, payload in sheets.items():
        values = sheet_values(payload)
        tables[sheet_name] = rows_from_values(values)
    return tables


def sheet_ids_from_snapshot(snapshot: dict[str, Any]) -> dict[str, int]:
    sheets = snapshot.get("sheets")
    if not isinstance(sheets, dict):
        raise ValueError("Snapshot must include a sheets object.")
    ids: dict[str, int] = {}
    for sheet_name, payload in sheets.items():
        if isinstance(payload, dict) and payload.get("sheet_id") is not None:
            ids[str(sheet_name)] = int(payload["sheet_id"])
    return ids


def sheet_values(payload: Any) -> list[list[Any]]:
    if isinstance(payload, dict):
        values = payload.get("values", [])
    else:
        values = payload
    if not isinstance(values, list):
        raise ValueError("Snapshot sheet values must be a list of rows.")
    return [list(row) if isinstance(row, list) else [row] for row in values]


def snapshot_from_tables(
    tables: dict[str, list[dict[str, Any]]],
    sheet_ids: dict[str, int] | None = None,
) -> dict[str, Any]:
    sheet_ids = sheet_ids or {}
    sheets: dict[str, Any] = {}
    for sheet_name, rows in tables.items():
        headers = list(sheet_by_name(sheet_name).headers)
        values = [headers]
        values.extend([[row.get(header, "") for header in headers] for row in rows])
        sheets[sheet_name] = {
            "sheet_id": sheet_ids.get(sheet_name),
            "values": values,
        }
    return {
        "schema": "lab-notebook-agent-google-sheets-snapshot.v1",
        "sheets": sheets,
    }


def snapshot_capture_plan(
    spreadsheet_id: str = "",
    value_range: str = "A1:Z1000",
) -> dict[str, Any]:
    return {
        "schema": "lab-notebook-agent-google-sheets-capture-plan.v1",
        "spreadsheet_id": spreadsheet_id,
        "value_render_option": "FORMATTED_VALUE",
        "sheets": [
            {
                "sheet_name": spec.name,
                "range": value_range,
                "headers": list(spec.headers),
                "used_for_apply": spec.name in {
                    "Master Reagents",
                    "Experiments",
                    "Formulations",
                    "Results",
                    "Literature Evidence",
                    "Agent Suggestions",
                    "Daily Reviews",
                },
            }
            for spec in SHEETS
        ],
    }


def validate_snapshot(snapshot: dict[str, Any], require_sheet_ids: bool = False) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    sheets = snapshot.get("sheets")
    if not isinstance(sheets, dict):
        return {
            "valid": False,
            "errors": [{"code": "missing_sheets_object", "message": "Snapshot must include a sheets object."}],
            "warnings": [],
            "summary": {},
        }

    for spec in SHEETS:
        payload = sheets.get(spec.name)
        if payload is None:
            errors.append({"code": "missing_sheet", "sheet": spec.name})
            continue
        values = sheet_values(payload)
        actual_headers = [str(value) for value in values[0]] if values else []
        expected_headers = list(spec.headers)
        if actual_headers[: len(expected_headers)] != expected_headers:
            errors.append(
                {
                    "code": "header_mismatch",
                    "sheet": spec.name,
                    "expected": expected_headers,
                    "actual": actual_headers,
                }
            )
        if require_sheet_ids and (not isinstance(payload, dict) or payload.get("sheet_id") is None):
            errors.append({"code": "missing_sheet_id", "sheet": spec.name})
        if len(actual_headers) > len(expected_headers):
            warnings.append(
                {
                    "code": "extra_columns",
                    "sheet": spec.name,
                    "expected_count": len(expected_headers),
                    "actual_count": len(actual_headers),
                }
            )

    unknown_sheets = sorted(set(sheets) - {sheet.name for sheet in SHEETS})
    for sheet_name in unknown_sheets:
        warnings.append({"code": "unknown_sheet", "sheet": sheet_name})

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "sheet_count": len(sheets),
            "missing_sheet_count": sum(1 for error in errors if error.get("code") == "missing_sheet"),
            "header_mismatch_count": sum(1 for error in errors if error.get("code") == "header_mismatch"),
            "warning_count": len(warnings),
        },
    }


def audit_report_against_snapshot(
    report: dict[str, Any],
    snapshot: dict[str, Any],
    require_sheet_ids: bool = True,
) -> dict[str, Any]:
    snapshot_audit = validate_snapshot(snapshot, require_sheet_ids=False)
    errors: list[dict[str, Any]] = list(snapshot_audit["errors"])
    warnings: list[dict[str, Any]] = list(snapshot_audit["warnings"])
    tables = snapshot_to_tables(snapshot) if snapshot_audit["valid"] or "sheets" in snapshot else {}
    sheet_ids = sheet_ids_from_snapshot(snapshot) if isinstance(snapshot.get("sheets"), dict) else {}

    evidence_rows = collect_rows(report, "append_literature_evidence")
    suggestion_rows = [
        suggestion_to_workbook_row(suggestion)
        for suggestion in collect_rows(report, "append_agent_suggestions")
    ]
    master_reagent_rows = collect_rows(report, "append_master_reagents")
    formulation_rows = collect_rows(report, "append_formulations")
    experiment_rows = collect_rows(report, "append_experiments")
    result_rows = collect_rows(report, "append_results")
    daily_review_rows = collect_rows(report, "append_daily_reviews")
    experiment_updates = collect_rows(report, "update_experiments")
    suggestion_updates = collect_rows(report, "update_agent_suggestions")
    for row in master_reagent_rows:
        reagent_id = str(row.get("reagent_id", ""))
        if reagent_id and any(str(existing.get("reagent_id", "")) == reagent_id for existing in tables.get("Master Reagents", [])):
            errors.append({"code": "duplicate_append", "sheet": "Master Reagents", "key": "reagent_id", "value": reagent_id})
    existing_formulation_keys = {formulation_key(row) for row in tables.get("Formulations", [])}
    for row in formulation_rows:
        row_key = formulation_key(row)
        if row_key in existing_formulation_keys:
            errors.append(
                {
                    "code": "duplicate_append",
                    "sheet": "Formulations",
                    "key": "experiment_id,reagent_id,target_role",
                    "value": "|".join(row_key),
                }
            )
    for row in evidence_rows:
        evidence_id = str(row.get("evidence_id", ""))
        if evidence_id and any(str(existing.get("evidence_id", "")) == evidence_id for existing in tables.get("Literature Evidence", [])):
            errors.append({"code": "duplicate_append", "sheet": "Literature Evidence", "key": "evidence_id", "value": evidence_id})
    for row in suggestion_rows:
        suggestion_id = str(row.get("suggestion_id", ""))
        if suggestion_id and any(str(existing.get("suggestion_id", "")) == suggestion_id for existing in tables.get("Agent Suggestions", [])):
            errors.append({"code": "duplicate_append", "sheet": "Agent Suggestions", "key": "suggestion_id", "value": suggestion_id})
    for update in suggestion_updates:
        suggestion_id = str(update.get("suggestion_id", ""))
        if suggestion_id and not any(str(existing.get("suggestion_id", "")) == suggestion_id for existing in tables.get("Agent Suggestions", [])):
            errors.append({"code": "missing_update_target", "sheet": "Agent Suggestions", "key": "suggestion_id", "value": suggestion_id})
    for update in experiment_updates:
        experiment_id = str(update.get("experiment_id", "") or update.get("key_value", ""))
        if experiment_id and not any(str(existing.get("experiment_id", "")) == experiment_id for existing in tables.get("Experiments", [])):
            errors.append({"code": "missing_update_target", "sheet": "Experiments", "key": "experiment_id", "value": experiment_id})
    for row in experiment_rows:
        experiment_id = str(row.get("experiment_id", ""))
        if experiment_id and any(str(existing.get("experiment_id", "")) == experiment_id for existing in tables.get("Experiments", [])):
            errors.append({"code": "duplicate_append", "sheet": "Experiments", "key": "experiment_id", "value": experiment_id})
    existing_result_keys = {result_row_key(row) for row in tables.get("Results", [])}
    for row in result_rows:
        row_key = result_row_key(row)
        if row_key in existing_result_keys:
            errors.append(
                {
                    "code": "duplicate_append",
                    "sheet": "Results",
                    "key": "experiment_id,sample_id,measurement_type",
                    "value": "|".join(row_key),
                }
            )
    for row in daily_review_rows:
        review_id = str(row.get("review_id", ""))
        if review_id and any(str(existing.get("review_id", "")) == review_id for existing in tables.get("Daily Reviews", [])):
            errors.append({"code": "duplicate_append", "sheet": "Daily Reviews", "key": "review_id", "value": review_id})

    if require_sheet_ids and evidence_rows and "Literature Evidence" not in sheet_ids:
        errors.append({"code": "missing_apply_sheet_id", "sheet": "Literature Evidence"})
    if require_sheet_ids and suggestion_rows and "Agent Suggestions" not in sheet_ids:
        errors.append({"code": "missing_apply_sheet_id", "sheet": "Agent Suggestions"})
    if require_sheet_ids and suggestion_updates and "Agent Suggestions" not in sheet_ids:
        errors.append({"code": "missing_apply_sheet_id", "sheet": "Agent Suggestions"})
    if require_sheet_ids and master_reagent_rows and "Master Reagents" not in sheet_ids:
        errors.append({"code": "missing_apply_sheet_id", "sheet": "Master Reagents"})
    if require_sheet_ids and formulation_rows and "Formulations" not in sheet_ids:
        errors.append({"code": "missing_apply_sheet_id", "sheet": "Formulations"})
    if require_sheet_ids and experiment_rows and "Experiments" not in sheet_ids:
        errors.append({"code": "missing_apply_sheet_id", "sheet": "Experiments"})
    if require_sheet_ids and experiment_updates and "Experiments" not in sheet_ids:
        errors.append({"code": "missing_apply_sheet_id", "sheet": "Experiments"})
    if require_sheet_ids and result_rows and "Results" not in sheet_ids:
        errors.append({"code": "missing_apply_sheet_id", "sheet": "Results"})
    if require_sheet_ids and daily_review_rows and "Daily Reviews" not in sheet_ids:
        errors.append({"code": "missing_apply_sheet_id", "sheet": "Daily Reviews"})

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "master_reagent_rows_to_append": len(master_reagent_rows),
            "formulation_rows_to_append": len(formulation_rows),
            "evidence_rows_to_append": len(evidence_rows),
            "suggestion_rows_to_append": len(suggestion_rows),
            "suggestion_rows_to_update": len(suggestion_updates),
            "experiment_rows_to_append": len(experiment_rows),
            "experiment_cells_to_update": len(experiment_updates),
            "result_rows_to_append": len(result_rows),
            "daily_review_rows_to_append": len(daily_review_rows),
            "request_count": len(batch_update_requests_from_report(report, sheet_ids)) if not errors else 0,
        },
    }


def batch_update_requests_from_report(
    report: dict[str, Any],
    sheet_ids: dict[str, int],
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    evidence_rows = collect_rows(report, "append_literature_evidence")
    suggestion_rows = [
        suggestion_to_workbook_row(suggestion)
        for suggestion in collect_rows(report, "append_agent_suggestions")
    ]
    master_reagent_rows = collect_rows(report, "append_master_reagents")
    formulation_rows = collect_rows(report, "append_formulations")
    experiment_rows = collect_rows(report, "append_experiments")
    result_rows = collect_rows(report, "append_results")
    daily_review_rows = collect_rows(report, "append_daily_reviews")
    experiment_updates = collect_rows(report, "update_experiments")
    suggestion_updates = collect_rows(report, "update_agent_suggestions")
    if master_reagent_rows:
        requests.append(append_cells_request("Master Reagents", master_reagent_rows, sheet_ids))
    if experiment_rows:
        requests.append(append_cells_request("Experiments", experiment_rows, sheet_ids))
    if formulation_rows:
        requests.append(append_cells_request("Formulations", formulation_rows, sheet_ids))
    if result_rows:
        requests.append(append_cells_request("Results", result_rows, sheet_ids))
    if evidence_rows:
        requests.append(append_cells_request("Literature Evidence", evidence_rows, sheet_ids))
    if suggestion_rows:
        requests.append(append_cells_request("Agent Suggestions", suggestion_rows, sheet_ids))
    if daily_review_rows:
        requests.append(append_cells_request("Daily Reviews", daily_review_rows, sheet_ids))
    for update in experiment_updates:
        requests.append(update_cell_request("Experiments", update, sheet_ids))
    for update in suggestion_updates:
        requests.append(update_cell_request("Agent Suggestions", update, sheet_ids))
    return requests


def append_cells_request(
    sheet_name: str,
    rows: list[dict[str, Any]],
    sheet_ids: dict[str, int],
) -> dict[str, Any]:
    if sheet_name not in sheet_ids:
        raise KeyError(f"Missing sheet ID for {sheet_name!r}.")
    headers = list(sheet_by_name(sheet_name).headers)
    return {
        "appendCells": {
            "sheetId": sheet_ids[sheet_name],
            "rows": [
                {
                    "values": [
                        {"userEnteredValue": {"stringValue": stringify_cell(row.get(header, ""))}}
                        for header in headers
                    ]
                }
                for row in rows
            ],
            "fields": "userEnteredValue",
        }
    }


def update_cell_request(
    sheet_name: str,
    update: dict[str, Any],
    sheet_ids: dict[str, int],
) -> dict[str, Any]:
    if sheet_name not in sheet_ids:
        raise KeyError(f"Missing sheet ID for {sheet_name!r}.")
    headers = list(sheet_by_name(sheet_name).headers)
    field = str(update.get("field", ""))
    if field not in headers:
        raise KeyError(f"Unknown field {field!r} for {sheet_name!r}.")
    row_number = int(update.get("row_number", 0))
    if row_number < 2:
        raise ValueError("Update row_number must be a 1-based sheet row number greater than or equal to 2.")
    return {
        "updateCells": {
            "start": {
                "sheetId": sheet_ids[sheet_name],
                "rowIndex": row_number - 1,
                "columnIndex": headers.index(field),
            },
            "rows": [
                {
                    "values": [
                        {"userEnteredValue": {"stringValue": stringify_cell(update.get("value", ""))}}
                    ]
                }
            ],
            "fields": "userEnteredValue",
        }
    }


def collect_rows(report: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in report.get(key, []) or []:
        if isinstance(row, dict):
            rows.append(row)
    for run in report.get("runs", []):
        for row in run.get(key, []) or []:
            if isinstance(row, dict):
                rows.append(row)
    return rows


def stringify_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return str(value)
