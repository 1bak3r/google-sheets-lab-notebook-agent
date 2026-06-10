from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from .material_scaffold import formulation_key
from .sheets import append_rows_to_workbook, update_workbook_rows_by_key


ACCEPTED_SUGGESTION_STATUSES = {"accepted"}


def build_plan_materialization_report(
    tables: dict[str, list[dict[str, Any]]],
    planned_date: str | None = None,
    suggestion_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    planned_date = planned_date or date.today().isoformat()
    requested_ids = set(suggestion_ids)
    existing_experiment_ids = {
        str(row.get("experiment_id", "")).strip()
        for row in tables.get("Experiments", [])
        if row.get("experiment_id")
    }
    existing_result_keys = {result_row_key(row) for row in tables.get("Results", [])}
    existing_formulation_keys = {formulation_key(row) for row in tables.get("Formulations", [])}
    runs = []

    for suggestion_index, suggestion in enumerate(tables.get("Agent Suggestions", []), start=2):
        suggestion_id = str(suggestion.get("suggestion_id", "")).strip()
        if requested_ids and suggestion_id not in requested_ids:
            continue
        status = str(suggestion.get("status", "")).strip().lower()
        if status not in ACCEPTED_SUGGESTION_STATUSES:
            continue

        plan = parse_suggestion_plan(suggestion)
        if not plan:
            runs.append(
                {
                    "suggestion_id": suggestion_id,
                    "status": "skipped",
                    "skip_reason": "missing_proposed_plan_json",
                    "append_experiments": [],
                    "append_formulations": [],
                    "append_results": [],
                    "update_agent_suggestions": [],
                }
            )
            continue

        proposed_experiment_id = proposed_id_from_suggestion(suggestion, plan)
        status_update = suggestion_status_update(
            suggestion,
            row_number=suggestion_index,
            value="run_planned",
        )
        experiment_rows = [
            row
            for row in experiment_rows_from_plan(suggestion, plan, planned_date)
            if str(row.get("experiment_id", "")).strip() not in existing_experiment_ids
        ]
        formulation_rows = [
            row
            for row in formulation_rows_from_plan(suggestion, plan)
            if formulation_key(row) not in existing_formulation_keys
        ]
        result_rows = [
            row
            for row in result_rows_from_plan(suggestion, plan)
            if result_row_key(row) not in existing_result_keys
        ]

        if not experiment_rows and not formulation_rows and not result_rows:
            runs.append(
                {
                    "suggestion_id": suggestion_id,
                    "experiment_id": proposed_experiment_id,
                    "status": "skipped",
                    "skip_reason": "planned_rows_already_exist",
                    "append_experiments": [],
                    "append_formulations": [],
                    "append_results": [],
                    "update_agent_suggestions": [status_update],
                }
            )
            continue

        for row in experiment_rows:
            existing_experiment_ids.add(str(row.get("experiment_id", "")).strip())
        for row in formulation_rows:
            existing_formulation_keys.add(formulation_key(row))
        for row in result_rows:
            existing_result_keys.add(result_row_key(row))

        runs.append(
            {
                "suggestion_id": suggestion_id,
                "experiment_id": proposed_experiment_id,
                "status": "ready",
                "append_experiments": experiment_rows,
                "append_formulations": formulation_rows,
                "append_results": result_rows,
                "update_agent_suggestions": [status_update],
            }
        )

    return {
        "schema": "lab-notebook-agent-plan-materialization.v1",
        "summary": summarize_plan_runs(runs),
        "runs": runs,
    }


def apply_plan_materialization_report_to_workbook(
    workbook_path: str | Path,
    report: dict[str, Any],
    output_workbook: str | Path | None = None,
) -> Path:
    destination = Path(output_workbook).expanduser().resolve() if output_workbook else Path(workbook_path).expanduser().resolve()
    current = Path(workbook_path).expanduser().resolve()
    for run in report.get("runs", []):
        experiment_rows = run.get("append_experiments", [])
        formulation_rows = run.get("append_formulations", [])
        result_rows = run.get("append_results", [])
        suggestion_updates = run.get("update_agent_suggestions", [])
        if experiment_rows:
            append_rows_to_workbook(current, "Experiments", experiment_rows, destination)
            current = destination
        if formulation_rows:
            append_rows_to_workbook(current, "Formulations", formulation_rows, destination)
            current = destination
        if result_rows:
            append_rows_to_workbook(current, "Results", result_rows, destination)
            current = destination
        if suggestion_updates:
            update_workbook_rows_by_key(current, "Agent Suggestions", suggestion_updates, destination)
            current = destination
    return destination


def parse_suggestion_plan(suggestion: dict[str, Any]) -> dict[str, Any] | None:
    direct_plan = suggestion.get("proposed_experiment_plan")
    if isinstance(direct_plan, dict):
        return direct_plan
    raw_plan = suggestion.get("proposed_plan_json", "")
    if isinstance(raw_plan, dict):
        return raw_plan
    if not isinstance(raw_plan, str) or not raw_plan.strip():
        return None
    try:
        parsed = json.loads(raw_plan)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def proposed_id_from_suggestion(suggestion: dict[str, Any], plan: dict[str, Any]) -> str:
    return str(
        suggestion.get("proposed_experiment_id")
        or plan.get("suggested_experiment_id")
        or f"{suggestion.get('experiment_id', 'EXP')}-FUP-001"
    )


def experiment_rows_from_plan(
    suggestion: dict[str, Any],
    plan: dict[str, Any],
    planned_date: str,
) -> list[dict[str, Any]]:
    sheet_rows = plan.get("sheet_rows", {}) if isinstance(plan.get("sheet_rows"), dict) else {}
    raw_rows = sheet_rows.get("experiments", [])
    if not isinstance(raw_rows, list) or not raw_rows:
        raw_rows = [
            {
                "experiment_id": proposed_id_from_suggestion(suggestion, plan),
                "process_type": plan.get("process_type", ""),
                "objective": plan.get("objective", ""),
                "hypothesis": plan.get("hypothesis", ""),
                "linked_literature_ids": ",".join(plan.get("linked_evidence_ids", []) or []),
                "status": "planned",
            }
        ]

    rows = []
    for raw_row in raw_rows:
        row = dict(raw_row) if isinstance(raw_row, dict) else {}
        row.setdefault("experiment_id", proposed_id_from_suggestion(suggestion, plan))
        row.setdefault("date", planned_date)
        if not row.get("date"):
            row["date"] = planned_date
        row.setdefault("project", "")
        row.setdefault("process_type", plan.get("process_type", ""))
        row.setdefault("objective", plan.get("objective", ""))
        row.setdefault("hypothesis", plan.get("hypothesis", ""))
        if not row.get("linked_literature_ids"):
            row["linked_literature_ids"] = ",".join(plan.get("linked_evidence_ids", []) or [])
        row.setdefault("operator", "")
        row.setdefault("status", "planned")
        row.setdefault("planned_next_step", f"Review accepted suggestion {suggestion.get('suggestion_id', '')} before running.")
        row.setdefault("summary", "")
        rows.append(row)
    return rows


def formulation_rows_from_plan(suggestion: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    suggested_experiment_id = proposed_id_from_suggestion(suggestion, plan)
    sheet_rows = plan.get("sheet_rows", {}) if isinstance(plan.get("sheet_rows"), dict) else {}
    raw_rows = sheet_rows.get("formulations", [])
    if not isinstance(raw_rows, list):
        return []
    rows = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            continue
        row = dict(raw_row)
        row.setdefault("experiment_id", suggested_experiment_id)
        if not row.get("experiment_id"):
            row["experiment_id"] = suggested_experiment_id
        row.setdefault("reagent_id", "")
        row.setdefault("phase", "")
        row.setdefault("target_role", "")
        row.setdefault("mass_g", "")
        row.setdefault("volume_mL", "")
        row.setdefault("moles_mmol", "")
        row.setdefault("concentration", "")
        row.setdefault("concentration_units", "")
        row.setdefault("wt_percent", "")
        row.setdefault("feed_order", "")
        row.setdefault("feed_start_min", "")
        row.setdefault("feed_duration_min", "")
        row.setdefault(
            "notes",
            f"Draft formulation row from accepted suggestion {suggestion.get('suggestion_id', '')}.",
        )
        if row.get("reagent_id") and row.get("target_role"):
            rows.append(row)
    return rows


def result_rows_from_plan(suggestion: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    suggested_experiment_id = proposed_id_from_suggestion(suggestion, plan)
    sheet_rows = plan.get("sheet_rows", {}) if isinstance(plan.get("sheet_rows"), dict) else {}
    raw_measurements = sheet_rows.get("results_to_capture", [])
    if not isinstance(raw_measurements, list) or not raw_measurements:
        raw_measurements = plan.get("measurements", [])
    rows = []
    for index, measurement in enumerate(raw_measurements, start=1):
        if isinstance(measurement, dict):
            measurement_type = str(measurement.get("measurement_type", "")).strip()
            units = str(measurement.get("units", "")).strip()
            method = str(measurement.get("method", "")).strip()
            condition = str(measurement.get("condition", "planned capture")).strip()
        else:
            measurement_type = str(measurement).strip()
            units = ""
            method = ""
            condition = "planned capture"
        if not measurement_type:
            continue
        rows.append(
            {
                "experiment_id": suggested_experiment_id,
                "sample_id": f"{suggested_experiment_id}-PLAN-{index:02d}",
                "measurement_type": measurement_type,
                "method": method,
                "value": "",
                "units": units,
                "condition": condition or "planned capture",
                "replicate": "",
                "quality_flag": "planned",
                "interpretation": f"Planned capture from suggestion {suggestion.get('suggestion_id', '')}.",
            }
        )
    return rows


def result_row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("experiment_id", "")).strip(),
        str(row.get("sample_id", "")).strip(),
        str(row.get("measurement_type", "")).strip(),
    )


def suggestion_status_update(
    suggestion: dict[str, Any],
    row_number: int,
    value: str,
) -> dict[str, Any]:
    return {
        "sheet": "Agent Suggestions",
        "row_number": row_number,
        "suggestion_id": suggestion.get("suggestion_id", ""),
        "key_field": "suggestion_id",
        "key_value": suggestion.get("suggestion_id", ""),
        "field": "status",
        "value": value,
    }


def summarize_plan_runs(runs: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(runs),
        "ready": sum(1 for run in runs if run.get("status") == "ready"),
        "skipped": sum(1 for run in runs if run.get("status") == "skipped"),
        "experiment_rows_to_append": sum(len(run.get("append_experiments", [])) for run in runs),
        "formulation_rows_to_append": sum(len(run.get("append_formulations", [])) for run in runs),
        "result_rows_to_append": sum(len(run.get("append_results", [])) for run in runs),
        "suggestion_rows_to_update": sum(len(run.get("update_agent_suggestions", [])) for run in runs),
    }
