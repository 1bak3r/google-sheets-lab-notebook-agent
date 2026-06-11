from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from .agent import AgentRunConfig, suggestion_to_workbook_row
from .daily_agent import build_daily_agent_run, build_daily_apply_report, empty_daily_agent_run
from .experiment_record import build_experiment_record_report
from .google_sheets import (
    audit_report_against_snapshot,
    batch_update_requests_from_report,
    sheet_ids_from_snapshot,
    snapshot_to_tables,
    validate_snapshot,
)
from .sheets import append_rows_to_workbook, load_workbook_tables, update_workbook_rows_by_key


def build_recorded_daily_agent_run(
    tables: dict[str, list[dict[str, Any]]],
    record: dict[str, Any],
    config: AgentRunConfig,
) -> dict[str, Any]:
    record_report = build_experiment_record_report(record, tables=tables)
    effective_config = config_for_record(config, record_report)
    projected_tables = tables_with_record_report(tables, record_report)
    daily_run = build_daily_agent_run(projected_tables, effective_config)
    apply_report = build_recorded_daily_apply_report(record_report, daily_run)
    return {
        "schema": "lab-notebook-agent-recorded-daily-run.v1",
        "experiment_id": record_report["experiment_id"],
        "review_date": effective_config.review_date or "",
        "selection": {
            "requested_experiment_ids": list(effective_config.experiment_ids),
            "selected_experiment_ids": daily_run.get("selection", {}).get("selected_experiment_ids", []),
        },
        "summary": combined_recorded_summary(record_report, daily_run, apply_report),
        "record_report": record_report,
        "daily_agent_run": daily_run,
        "apply_report": apply_report,
    }


def build_snapshot_recorded_daily_agent_run(
    snapshot: dict[str, Any],
    record: dict[str, Any],
    config: AgentRunConfig,
) -> dict[str, Any]:
    snapshot_audit = validate_snapshot(snapshot, require_sheet_ids=False)
    if snapshot_audit["valid"]:
        run = build_recorded_daily_agent_run(snapshot_to_tables(snapshot), record, config)
    else:
        record_report = build_experiment_record_report(record)
        effective_config = config_for_record(config, record_report)
        daily_run = empty_daily_agent_run(effective_config, effective_config.review_date or "")
        run = {
            "schema": "lab-notebook-agent-recorded-daily-run.v1",
            "experiment_id": record_report["experiment_id"],
            "review_date": effective_config.review_date or "",
            "selection": {
                "requested_experiment_ids": list(effective_config.experiment_ids),
                "selected_experiment_ids": [],
            },
            "summary": combined_recorded_summary(record_report, daily_run, record_report),
            "record_report": record_report,
            "daily_agent_run": daily_run,
            "apply_report": record_report,
        }
    apply_report = run.get("apply_report", {})
    apply_audit = audit_report_against_snapshot(apply_report, snapshot, require_sheet_ids=True)
    requests = batch_update_requests_from_report(apply_report, sheet_ids_from_snapshot(snapshot)) if apply_audit["valid"] else []
    run["snapshot_audit"] = snapshot_audit
    run["apply_audit"] = apply_audit
    run["batch_update_requests"] = requests
    run["summary"]["snapshot_audit_valid"] = snapshot_audit["valid"]
    run["summary"]["apply_audit_valid"] = apply_audit["valid"]
    run["summary"]["apply_request_count"] = len(requests)
    return run


def run_workbook_recorded_daily_agent(
    workbook_path: str | Path,
    record: dict[str, Any],
    config: AgentRunConfig,
    apply: bool = False,
    output_workbook: str | Path | None = None,
) -> dict[str, Any]:
    run = build_recorded_daily_agent_run(load_workbook_tables(workbook_path), record, config)
    if apply:
        apply_recorded_daily_agent_run_to_workbook(
            workbook_path,
            run,
            output_workbook=output_workbook,
        )
    run["applied"] = bool(apply)
    return run


def apply_recorded_daily_agent_run_to_workbook(
    workbook_path: str | Path,
    run: dict[str, Any],
    output_workbook: str | Path | None = None,
) -> Path:
    destination = Path(output_workbook).expanduser().resolve() if output_workbook else Path(workbook_path).expanduser().resolve()
    current = Path(workbook_path).expanduser().resolve()
    apply_report = run.get("apply_report", {})
    for sheet_name, report_key in (
        ("Master Reagents", "append_master_reagents"),
        ("Experiments", "append_experiments"),
        ("Formulations", "append_formulations"),
        ("Daily Log", "append_daily_log"),
        ("Results", "append_results"),
    ):
        rows = dict_rows(apply_report.get(report_key, []))
        if rows:
            append_rows_to_workbook(current, sheet_name, rows, destination)
            current = destination

    master_reagent_updates = dict_rows(apply_report.get("update_master_reagents", []))
    if master_reagent_updates:
        update_workbook_rows_by_key(current, "Master Reagents", master_reagent_updates, output_path=destination)
        current = destination

    run_rows = dict_rows(apply_report.get("runs", []))
    result_rows = nested_report_rows(run_rows, "append_results")
    if result_rows:
        append_rows_to_workbook(current, "Results", result_rows, destination)
        current = destination
    evidence_rows = nested_report_rows(run_rows, "append_literature_evidence")
    if evidence_rows:
        append_rows_to_workbook(current, "Literature Evidence", evidence_rows, destination)
        current = destination
    suggestion_rows = nested_report_rows(run_rows, "append_agent_suggestions")
    if suggestion_rows:
        append_rows_to_workbook(
            current,
            "Agent Suggestions",
            [suggestion_to_workbook_row(row) for row in suggestion_rows],
            destination,
        )
        current = destination
    daily_review_rows = dict_rows(apply_report.get("append_daily_reviews", []))
    if daily_review_rows:
        append_rows_to_workbook(current, "Daily Reviews", daily_review_rows, destination)
        current = destination
    experiment_updates = dict_rows(apply_report.get("update_experiments", []))
    if experiment_updates:
        update_workbook_rows_by_key(current, "Experiments", experiment_updates, output_path=destination)
        current = destination
    suggestion_updates = dict_rows(apply_report.get("update_agent_suggestions", []))
    if suggestion_updates:
        update_workbook_rows_by_key(current, "Agent Suggestions", suggestion_updates, output_path=destination)
    return destination


def build_recorded_daily_apply_report(
    record_report: dict[str, Any],
    daily_run: dict[str, Any],
) -> dict[str, Any]:
    daily_apply_report = build_daily_apply_report(daily_run)
    experiment_rows = [dict(row) for row in record_report.get("append_experiments", []) if isinstance(row, dict)]
    updates = merge_new_experiment_updates(experiment_rows, daily_apply_report.get("update_experiments", []))
    daily_summary = daily_apply_report.get("summary", {}) if isinstance(daily_apply_report.get("summary"), dict) else {}
    record_summary = record_report.get("summary", {}) if isinstance(record_report.get("summary"), dict) else {}
    return {
        "schema": "lab-notebook-agent-recorded-daily-apply.v1",
        "summary": {
            "master_reagent_rows_to_append": int(record_summary.get("master_reagent_rows_to_append", 0) or 0),
            "master_reagent_cells_to_update": int(record_summary.get("master_reagent_cells_to_update", 0) or 0),
            "experiment_rows_to_append": len(experiment_rows),
            "formulation_rows_to_append": int(record_summary.get("formulation_rows_to_append", 0) or 0),
            "daily_log_rows_to_append": int(record_summary.get("daily_log_rows_to_append", 0) or 0),
            "record_result_rows_to_append": int(record_summary.get("result_rows_to_append", 0) or 0),
            "normalized_result_rows_to_append": int(daily_summary.get("result_rows_to_append", 0) or 0),
            "evidence_rows_to_append": int(daily_summary.get("evidence_rows_to_append", 0) or 0),
            "suggestion_rows_to_append": int(daily_summary.get("suggestion_rows_to_append", 0) or 0),
            "suggestion_rows_to_update": int(daily_summary.get("suggestion_rows_to_update", 0) or 0),
            "daily_review_rows_to_append": int(daily_summary.get("daily_review_rows_to_append", 0) or 0),
            "experiment_cells_to_update": len(updates),
        },
        "append_master_reagents": record_report.get("append_master_reagents", []),
        "update_master_reagents": record_report.get("update_master_reagents", []),
        "append_experiments": experiment_rows,
        "append_formulations": record_report.get("append_formulations", []),
        "append_daily_log": record_report.get("append_daily_log", []),
        "append_results": record_report.get("append_results", []),
        "append_daily_reviews": daily_apply_report.get("append_daily_reviews", []),
        "update_experiments": updates,
        "update_agent_suggestions": daily_apply_report.get("update_agent_suggestions", []),
        "runs": daily_apply_report.get("runs", []),
    }


def merge_new_experiment_updates(
    experiment_rows: list[dict[str, Any]],
    updates: Any,
) -> list[dict[str, Any]]:
    rows_by_id = {
        str(row.get("experiment_id", "")).strip(): row
        for row in experiment_rows
        if str(row.get("experiment_id", "")).strip()
    }
    remaining: list[dict[str, Any]] = []
    for update in updates or []:
        if not isinstance(update, dict):
            continue
        experiment_id = str(update.get("experiment_id", "") or update.get("key_value", "")).strip()
        target_field = str(update.get("field", "")).strip()
        if experiment_id in rows_by_id and target_field:
            rows_by_id[experiment_id][target_field] = update.get("value", "")
            continue
        remaining.append(update)
    return remaining


def dict_rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value or [] if isinstance(row, dict)]


def nested_report_rows(runs: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    rows = []
    for run in runs:
        rows.extend(dict_rows(run.get(key, [])))
    return rows


def tables_with_record_report(
    tables: dict[str, list[dict[str, Any]]],
    record_report: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    projected = {
        sheet_name: [dict(row) for row in rows if isinstance(row, dict)]
        for sheet_name, rows in tables.items()
    }
    for sheet_name, report_key in (
        ("Master Reagents", "append_master_reagents"),
        ("Experiments", "append_experiments"),
        ("Formulations", "append_formulations"),
        ("Daily Log", "append_daily_log"),
        ("Results", "append_results"),
    ):
        projected.setdefault(sheet_name, [])
        projected[sheet_name].extend(
            dict(row) for row in record_report.get(report_key, []) if isinstance(row, dict)
        )
    apply_projected_updates(projected, "Master Reagents", record_report.get("update_master_reagents", []))
    return projected


def apply_projected_updates(
    tables: dict[str, list[dict[str, Any]]],
    sheet_name: str,
    updates: Any,
) -> None:
    rows = tables.setdefault(sheet_name, [])
    for update in updates or []:
        if not isinstance(update, dict):
            continue
        key_field = str(update.get("key_field", "") or "reagent_id").strip()
        key_value = str(update.get("key_value", "") or update.get(key_field, "")).strip()
        target_field = str(update.get("field", "")).strip()
        if not key_field or not key_value or not target_field:
            continue
        for row in rows:
            if isinstance(row, dict) and str(row.get(key_field, "")).strip() == key_value:
                row[target_field] = update.get("value", "")
                break


def config_for_record(config: AgentRunConfig, record_report: dict[str, Any]) -> AgentRunConfig:
    experiment_id = str(record_report.get("experiment_id", "")).strip()
    experiment_ids = config.experiment_ids or ((experiment_id,) if experiment_id else ())
    review_date = config.review_date or review_date_from_record_report(record_report)
    return replace(config, experiment_ids=experiment_ids, review_date=review_date)


def review_date_from_record_report(record_report: dict[str, Any]) -> str:
    for row in record_report.get("append_experiments", []) or []:
        if isinstance(row, dict) and str(row.get("date", "")).strip():
            return str(row["date"]).strip()[:10]
    for row in record_report.get("append_daily_log", []) or []:
        if isinstance(row, dict) and str(row.get("timestamp", "")).strip():
            return str(row["timestamp"]).strip()[:10]
    return ""


def combined_recorded_summary(
    record_report: dict[str, Any],
    daily_run: dict[str, Any],
    apply_report: dict[str, Any],
) -> dict[str, Any]:
    record_summary = record_report.get("summary", {}) if isinstance(record_report.get("summary"), dict) else {}
    daily_summary = daily_run.get("summary", {}) if isinstance(daily_run.get("summary"), dict) else {}
    apply_summary = apply_report.get("summary", {}) if isinstance(apply_report.get("summary"), dict) else {}
    return {
        "record_master_reagent_rows_to_append": int(record_summary.get("master_reagent_rows_to_append", 0) or 0),
        "record_experiment_rows_to_append": int(record_summary.get("experiment_rows_to_append", 0) or 0),
        "record_formulation_rows_to_append": int(record_summary.get("formulation_rows_to_append", 0) or 0),
        "record_daily_log_rows_to_append": int(record_summary.get("daily_log_rows_to_append", 0) or 0),
        "record_result_rows_to_append": int(record_summary.get("result_rows_to_append", 0) or 0),
        "daily_experiment_count": int(daily_summary.get("experiment_count", 0) or 0),
        "daily_agent_runs_ready": int(daily_summary.get("agent_runs_ready", 0) or 0),
        "normalized_result_rows_to_append": int(daily_summary.get("normalized_result_rows_to_append", 0) or 0),
        "evidence_rows_to_append": int(daily_summary.get("evidence_rows_to_append", 0) or 0),
        "suggestion_rows_to_append": int(daily_summary.get("suggestion_rows_to_append", 0) or 0),
        "daily_review_rows_to_append": int(apply_summary.get("daily_review_rows_to_append", 0) or 0),
        "experiment_cells_to_update": int(apply_summary.get("experiment_cells_to_update", 0) or 0),
    }
