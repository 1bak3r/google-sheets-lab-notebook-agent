from __future__ import annotations

from pathlib import Path
from typing import Any

from .agent import AgentRunConfig, apply_agent_report_to_workbook, build_agent_report
from .daily_log_results import apply_daily_log_results_report_to_workbook, build_daily_log_results_report
from .daily_reviews import apply_daily_review_rows_to_workbook, daily_review_row_from_run
from .daily_summary import build_daily_summary_report
from .google_sheets import (
    audit_report_against_snapshot,
    batch_update_requests_from_report,
    sheet_ids_from_snapshot,
    snapshot_to_tables,
    validate_snapshot,
)
from .material_search import build_process_material_search_report
from .preflight import build_experiment_preflight_report
from .sheets import load_workbook_tables, update_workbook_rows_by_key


def build_daily_agent_run(
    tables: dict[str, list[dict[str, Any]]],
    config: AgentRunConfig,
) -> dict[str, Any]:
    review_date = require_review_date(config)
    daily_summary = build_daily_summary_report(
        tables,
        review_date=review_date,
        experiment_ids=config.experiment_ids,
    )
    agent_report = build_agent_report(tables, config=config)
    experiment_reviews = build_daily_experiment_reviews(
        tables,
        selected_experiment_ids(agent_report, daily_summary),
        daily_summary=daily_summary,
    )
    daily_log_results_report = build_daily_log_results_report(
        tables,
        experiment_ids=tuple(selected_experiment_ids(agent_report, daily_summary)),
        review_date=review_date,
    )
    run = assemble_daily_agent_run(
        daily_summary,
        agent_report,
        config,
        experiment_reviews,
        daily_log_results_report=daily_log_results_report,
    )
    run["update_experiments"] = build_daily_experiment_updates(tables, run)
    run["summary"]["experiment_cells_to_update"] = len(run["update_experiments"])
    return run


def build_snapshot_daily_agent_run(
    snapshot: dict[str, Any],
    config: AgentRunConfig,
) -> dict[str, Any]:
    review_date = require_review_date(config)
    snapshot_audit = validate_snapshot(snapshot, require_sheet_ids=False)
    if snapshot_audit["valid"]:
        run = build_daily_agent_run(snapshot_to_tables(snapshot), config)
    else:
        run = empty_daily_agent_run(config, review_date)

    apply_report = build_daily_apply_report(run)
    apply_audit = audit_report_against_snapshot(apply_report, snapshot, require_sheet_ids=True)
    requests = batch_update_requests_from_report(
        apply_report,
        sheet_ids_from_snapshot(snapshot),
    ) if apply_audit["valid"] else []
    run["apply_report"] = apply_report
    run["snapshot_audit"] = snapshot_audit
    run["apply_audit"] = apply_audit
    run["batch_update_requests"] = requests
    run["summary"]["apply_audit_valid"] = apply_audit["valid"]
    run["summary"]["apply_request_count"] = len(requests)
    return run


def run_workbook_daily_agent(
    workbook_path: str | Path,
    config: AgentRunConfig,
    apply: bool = False,
    output_workbook: str | Path | None = None,
) -> dict[str, Any]:
    run = build_daily_agent_run(load_workbook_tables(workbook_path), config)
    if apply:
        destination = Path(output_workbook).expanduser().resolve() if output_workbook else Path(workbook_path).expanduser().resolve()
        current = Path(workbook_path).expanduser().resolve()
        daily_log_results = run.get("daily_log_results_report", {})
        if daily_log_results.get("summary", {}).get("result_rows_to_append", 0):
            apply_daily_log_results_report_to_workbook(
                current,
                daily_log_results,
                output_workbook=destination,
            )
            current = destination
        apply_agent_report_to_workbook(
            current,
            run["agent_report"],
            output_workbook=destination,
        )
        current = destination
        apply_daily_review_rows_to_workbook(
            current,
            [daily_review_row_from_run(run)],
            output_workbook=destination,
        )
        current = destination
        experiment_updates = run.get("update_experiments", [])
        if experiment_updates:
            update_workbook_rows_by_key(
                current,
                "Experiments",
                experiment_updates,
                output_path=destination,
            )
    run["applied"] = bool(apply)
    return run


def assemble_daily_agent_run(
    daily_summary: dict[str, Any],
    agent_report: dict[str, Any],
    config: AgentRunConfig,
    experiment_reviews: list[dict[str, Any]] | None = None,
    daily_log_results_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    experiment_reviews = experiment_reviews or []
    daily_log_results_report = daily_log_results_report or empty_daily_log_results_report(config)
    return {
        "schema": "lab-notebook-agent-daily-run.v1",
        "review_date": require_review_date(config),
        "selection": {
            "requested_experiment_ids": list(config.experiment_ids),
            "selected_experiment_ids": agent_report.get("selection", {}).get("selected_experiment_ids", []),
            "daily_summary_selected_experiment_ids": daily_summary.get("selection", {}).get("selected_experiment_ids", []),
        },
        "summary": combined_summary(daily_summary, agent_report, experiment_reviews, daily_log_results_report),
        "experiment_reviews": experiment_reviews,
        "daily_log_results_report": daily_log_results_report,
        "daily_summary": daily_summary,
        "agent_report": agent_report,
    }


def combined_summary(
    daily_summary: dict[str, Any],
    agent_report: dict[str, Any],
    experiment_reviews: list[dict[str, Any]] | None = None,
    daily_log_results_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    experiment_reviews = experiment_reviews or []
    daily_log_results_summary = (
        daily_log_results_report.get("summary", {})
        if isinstance(daily_log_results_report, dict) and isinstance(daily_log_results_report.get("summary"), dict)
        else {}
    )
    daily_counts = daily_summary.get("summary", {}) if isinstance(daily_summary.get("summary"), dict) else {}
    agent_counts = agent_report.get("summary", {}) if isinstance(agent_report.get("summary"), dict) else {}
    return {
        "experiment_count": int(daily_counts.get("experiment_count", 0) or 0),
        "observation_count": int(daily_counts.get("observation_count", 0) or 0),
        "result_count": int(daily_counts.get("result_count", 0) or 0),
        "open_suggestion_count": int(daily_counts.get("open_suggestion_count", 0) or 0),
        "experiments_needing_material_attention": daily_counts.get("experiments_needing_material_attention", []),
        "agent_runs_total": int(agent_counts.get("total", 0) or 0),
        "agent_runs_ready": int(agent_counts.get("ready", 0) or 0),
        "agent_runs_skipped": int(agent_counts.get("skipped", 0) or 0),
        "evidence_rows_to_append": int(agent_counts.get("evidence_rows_to_append", 0) or 0),
        "suggestion_rows_to_append": int(agent_counts.get("suggestion_rows_to_append", 0) or 0),
        "normalized_result_rows_to_append": int(daily_log_results_summary.get("result_rows_to_append", 0) or 0),
        "daily_log_measurements_skipped": int(daily_log_results_summary.get("measurements_skipped", 0) or 0),
        "experiment_review_count": len(experiment_reviews),
        "preflight_fail_count": sum(int(row.get("preflight", {}).get("summary", {}).get("fail_count", 0) or 0) for row in experiment_reviews),
        "preflight_warn_count": sum(int(row.get("preflight", {}).get("summary", {}).get("warn_count", 0) or 0) for row in experiment_reviews),
        "ready_for_agent_suggestion_count": sum(1 for row in experiment_reviews if row.get("preflight", {}).get("ready_for_agent_suggestion")),
        "material_required_roles_missing_candidate_count": sum(
            len(row.get("material_search", {}).get("summary", {}).get("required_roles_missing_candidates", []) or [])
            for row in experiment_reviews
        ),
    }


def empty_daily_agent_run(config: AgentRunConfig, review_date: str) -> dict[str, Any]:
    daily_summary = {
        "schema": "lab-notebook-agent-daily-summary.v1",
        "review_date": review_date,
        "selection": {
            "requested_experiment_ids": list(config.experiment_ids),
            "selected_experiment_ids": [],
        },
        "summary": {
            "experiment_count": 0,
            "observation_count": 0,
            "result_count": 0,
            "open_suggestion_count": 0,
            "experiments_needing_material_attention": [],
        },
        "experiments": [],
    }
    agent_report = {
        "schema": "lab-notebook-agent-run.v1",
        "selection": {
            "requested_experiment_ids": list(config.experiment_ids),
            "review_date": review_date,
            "selected_experiment_ids": [],
        },
        "summary": {
            "total": 0,
            "ready": 0,
            "skipped": 0,
            "evidence_rows_to_append": 0,
            "suggestion_rows_to_append": 0,
        },
        "runs": [],
    }
    return assemble_daily_agent_run(
        daily_summary,
        agent_report,
        config,
        experiment_reviews=[],
        daily_log_results_report=empty_daily_log_results_report(config),
    )


def empty_daily_log_results_report(config: AgentRunConfig) -> dict[str, Any]:
    return {
        "schema": "lab-notebook-agent-daily-log-results.v1",
        "selection": {
            "requested_experiment_ids": list(config.experiment_ids),
            "review_date": config.review_date or "",
        },
        "summary": {
            "daily_log_rows_considered": 0,
            "ready": 0,
            "skipped": 0,
            "result_rows_to_append": 0,
            "measurements_skipped": 0,
        },
        "runs": [],
    }


def build_daily_apply_report(run: dict[str, Any]) -> dict[str, Any]:
    daily_log_results_report = run.get("daily_log_results_report", {})
    agent_report = run.get("agent_report", {})
    daily_log_runs = daily_log_results_report.get("runs", []) if isinstance(daily_log_results_report, dict) else []
    agent_runs = agent_report.get("runs", []) if isinstance(agent_report, dict) else []
    runs = [
        run_row
        for run_row in [*daily_log_runs, *agent_runs]
        if isinstance(run_row, dict)
    ]
    return {
        "schema": "lab-notebook-agent-daily-apply.v1",
        "summary": {
            "result_rows_to_append": sum(len(row.get("append_results", [])) for row in runs),
            "evidence_rows_to_append": sum(len(row.get("append_literature_evidence", [])) for row in runs),
            "suggestion_rows_to_append": sum(len(row.get("append_agent_suggestions", [])) for row in runs),
            "daily_review_rows_to_append": 1,
        },
        "append_daily_reviews": [daily_review_row_from_run(run)],
        "update_experiments": run.get("update_experiments", []),
        "runs": runs,
    }


def build_daily_experiment_updates(
    tables: dict[str, list[dict[str, Any]]],
    run: dict[str, Any],
) -> list[dict[str, Any]]:
    experiment_rows = [
        row
        for row in tables.get("Experiments", [])
        if isinstance(row, dict)
    ]
    experiments_by_id = {
        str(row.get("experiment_id", "")).strip(): (row_number, row)
        for row_number, row in enumerate(experiment_rows, start=2)
        if str(row.get("experiment_id", "")).strip()
    }
    summaries_by_id = {
        str(row.get("experiment_id", "")).strip(): row
        for row in run.get("daily_summary", {}).get("experiments", []) or []
        if isinstance(row, dict) and str(row.get("experiment_id", "")).strip()
    }
    reviews_by_id = {
        str(row.get("experiment_id", "")).strip(): row
        for row in run.get("experiment_reviews", []) or []
        if isinstance(row, dict) and str(row.get("experiment_id", "")).strip()
    }

    updates: list[dict[str, Any]] = []
    for experiment_id in run.get("selection", {}).get("selected_experiment_ids", []) or []:
        experiment_id = str(experiment_id).strip()
        if experiment_id not in experiments_by_id:
            continue
        row_number, experiment_row = experiments_by_id[experiment_id]
        experiment_summary = summaries_by_id.get(experiment_id, {})
        review = reviews_by_id.get(experiment_id, {})
        values = {
            "status": daily_experiment_status(experiment_row, experiment_summary, review, run),
            "planned_next_step": daily_experiment_next_step(experiment_id, review, run),
            "summary": daily_experiment_summary_text(experiment_id, experiment_summary, review, run),
        }
        for field, value in values.items():
            if not value:
                continue
            if str(experiment_row.get(field, "")).strip() == str(value).strip():
                continue
            updates.append(
                {
                    "sheet": "Experiments",
                    "row_number": row_number,
                    "experiment_id": experiment_id,
                    "key_field": "experiment_id",
                    "key_value": experiment_id,
                    "field": field,
                    "value": value,
                }
            )
    return updates


def daily_experiment_status(
    experiment_row: dict[str, Any],
    experiment_summary: dict[str, Any],
    review: dict[str, Any],
    run: dict[str, Any],
) -> str:
    current_status = str(experiment_row.get("status", "")).strip().lower()
    if current_status == "abandoned":
        return ""
    preflight_summary = review.get("preflight", {}).get("summary", {}) if isinstance(review.get("preflight"), dict) else {}
    if int(preflight_summary.get("fail_count", 0) or 0) > 0:
        return "needs_review"
    if daily_experiment_write_count(str(experiment_row.get("experiment_id", "")), run) > 0:
        return "needs_review"
    if int(preflight_summary.get("warn_count", 0) or 0) > 0:
        return "needs_review"
    if int(experiment_summary.get("observation_count", 0) or 0) or int(experiment_summary.get("result_count", 0) or 0):
        return "complete"
    return ""


def daily_experiment_next_step(experiment_id: str, review: dict[str, Any], run: dict[str, Any]) -> str:
    preflight = review.get("preflight", {}) if isinstance(review.get("preflight"), dict) else {}
    preflight_summary = preflight.get("summary", {}) if isinstance(preflight.get("summary"), dict) else {}
    next_actions = [str(action) for action in preflight.get("next_actions", []) or [] if str(action).strip()]
    if int(preflight_summary.get("fail_count", 0) or 0) > 0 and next_actions:
        return next_actions[0]
    if daily_experiment_count(experiment_id, run, "append_agent_suggestions"):
        return "Review draft Agent Suggestions and accept, reject, or revise the follow-up plan."
    if daily_experiment_count(experiment_id, run, "append_results"):
        return "Review normalized Daily Log measurements in Results."
    if daily_experiment_count(experiment_id, run, "append_literature_evidence"):
        return "Review appended Literature Evidence before relying on it."
    if next_actions:
        return next_actions[0]
    return "Daily review complete; no new agent write actions."


def daily_experiment_summary_text(
    experiment_id: str,
    experiment_summary: dict[str, Any],
    review: dict[str, Any],
    run: dict[str, Any],
) -> str:
    preflight_summary = review.get("preflight", {}).get("summary", {}) if isinstance(review.get("preflight"), dict) else {}
    return (
        f"Daily review {run.get('review_date', '')}: "
        f"{experiment_summary.get('observation_count', 0)} observations; "
        f"{experiment_summary.get('result_count', 0)} existing Results rows; "
        f"{daily_experiment_count(experiment_id, run, 'append_results')} normalized Results pending; "
        f"{daily_experiment_count(experiment_id, run, 'append_literature_evidence')} evidence rows pending; "
        f"{daily_experiment_count(experiment_id, run, 'append_agent_suggestions')} suggestion rows pending; "
        f"{preflight_summary.get('fail_count', 0)} preflight failures."
    )


def daily_experiment_write_count(experiment_id: str, run: dict[str, Any]) -> int:
    return sum(
        daily_experiment_count(experiment_id, run, key)
        for key in ("append_results", "append_literature_evidence", "append_agent_suggestions")
    )


def daily_experiment_count(experiment_id: str, run: dict[str, Any], key: str) -> int:
    total = 0
    reports = [
        run.get("daily_log_results_report", {}),
        run.get("agent_report", {}),
    ]
    for report in reports:
        for row in report.get("runs", []) if isinstance(report, dict) else []:
            if not isinstance(row, dict):
                continue
            if str(row.get("experiment_id", "")).strip() == experiment_id:
                total += len(row.get(key, []) or [])
    return total


def build_daily_experiment_reviews(
    tables: dict[str, list[dict[str, Any]]],
    experiment_ids: list[str],
    daily_summary: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    daily_summary = daily_summary or {}
    summaries_by_id = {
        str(row.get("experiment_id", "")): row
        for row in daily_summary.get("experiments", [])
        if isinstance(row, dict)
    }
    reviews = []
    for experiment_id in experiment_ids:
        preflight = build_experiment_preflight_report(
            tables,
            experiment_id=experiment_id,
            stage="review",
        )
        experiment_summary = summaries_by_id.get(experiment_id, {})
        material_search = build_process_material_search_report(
            tables,
            experiment_id=experiment_id,
            query=daily_material_search_query(experiment_summary, preflight),
        )
        reviews.append(
            {
                "experiment_id": experiment_id,
                "preflight": preflight,
                "material_search": material_search,
            }
        )
    return reviews


def selected_experiment_ids(agent_report: dict[str, Any], daily_summary: dict[str, Any]) -> list[str]:
    agent_ids = agent_report.get("selection", {}).get("selected_experiment_ids", [])
    if isinstance(agent_ids, list) and agent_ids:
        return [str(experiment_id) for experiment_id in agent_ids]
    summary_ids = daily_summary.get("selection", {}).get("selected_experiment_ids", [])
    if isinstance(summary_ids, list):
        return [str(experiment_id) for experiment_id in summary_ids]
    return []


def daily_material_search_query(experiment_summary: dict[str, Any], preflight: dict[str, Any]) -> str:
    parts: list[str] = []
    parts.append(str(experiment_summary.get("objective", "")))
    parts.extend(str(tag) for tag in experiment_summary.get("issue_tags", []) or [])
    for measurement in experiment_summary.get("measurements", []) or []:
        if not isinstance(measurement, dict):
            continue
        parts.extend(
            [
                str(measurement.get("measurement_type", "")),
                str(measurement.get("value", "")),
                str(measurement.get("units", "")),
                str(measurement.get("interpretation", "")),
            ]
        )
    material_summary = preflight.get("material_audit", {}).get("summary", "")
    parts.append(str(material_summary))
    return " ".join(part for part in parts if part.strip())


def require_review_date(config: AgentRunConfig) -> str:
    review_date = str(config.review_date or "").strip()
    if not review_date:
        raise ValueError("Daily agent runs require AgentRunConfig.review_date.")
    return review_date
