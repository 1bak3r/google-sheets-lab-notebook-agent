from __future__ import annotations

from typing import Any

from .agent import selected_experiment_ids, suggestions_for_experiment
from .materials import audit_experiment_materials
from .result_analysis import build_result_analysis
from .sheets import build_experiment_entry_from_tables


def build_daily_summary_report(
    tables: dict[str, list[dict[str, Any]]],
    review_date: str,
    experiment_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    selected_ids = selected_experiment_ids(
        tables,
        experiment_ids,
        review_date=review_date,
    )
    experiment_statuses = experiment_status_by_id(tables)
    experiments = []
    for experiment_id in selected_ids:
        entry = build_experiment_entry_from_tables(tables, experiment_id)
        material_audit = audit_experiment_materials(entry)
        observations = [row for row in entry.get("observations", []) if isinstance(row, dict)]
        results = [row for row in entry.get("results", []) if isinstance(row, dict)]
        suggestions = suggestions_for_experiment(tables, experiment_id)
        open_suggestions = suggestion_summaries(suggestions, experiment_statuses)
        result_analysis = build_result_analysis(entry)
        experiments.append(
            {
                "experiment_id": experiment_id,
                "date": entry.get("date", ""),
                "project": entry.get("project", ""),
                "process_type": entry.get("process_type", ""),
                "status": entry.get("status", ""),
                "objective": entry.get("objective", ""),
                "observation_count": len(observations),
                "result_count": len(results),
                "issue_tags": issue_tags(observations),
                "latest_observations": latest_observations(observations),
                "measurements": measurement_summaries(results),
                "result_analysis": compact_result_analysis(result_analysis),
                "result_analysis_summary": result_analysis.get("summary", ""),
                "result_signals": result_analysis.get("signals", []),
                "limiting_metrics": result_analysis.get("limiting_metrics", []),
                "material_audit_summary": material_audit.get("summary", ""),
                "ready_for_quantitative_suggestion": material_audit.get("ready_for_quantitative_suggestion", False),
                "material_recommendations": material_audit.get("recommendations", []),
                "open_suggestions": open_suggestions,
                "next_actions": next_actions(material_audit, results, open_suggestions, result_analysis),
            }
        )

    return {
        "schema": "lab-notebook-agent-daily-summary.v1",
        "review_date": review_date,
        "selection": {
            "requested_experiment_ids": list(experiment_ids),
            "selected_experiment_ids": selected_ids,
        },
        "summary": summarize_daily_experiments(experiments),
        "experiments": experiments,
    }


def issue_tags(observations: list[dict[str, Any]]) -> list[str]:
    tags = set()
    for row in observations:
        for tag in str(row.get("issue_tags", "")).split(","):
            normalized = tag.strip()
            if normalized:
                tags.add(normalized)
    return sorted(tags)


def latest_observations(observations: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    sorted_rows = sorted(observations, key=lambda row: str(row.get("timestamp", "")))
    return [
        {
            "timestamp": row.get("timestamp", ""),
            "process_stage": row.get("process_stage", ""),
            "observation": row.get("observation", ""),
            "issue_tags": row.get("issue_tags", ""),
        }
        for row in sorted_rows[-limit:]
    ]


def measurement_summaries(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "sample_id": row.get("sample_id", ""),
            "measurement_type": row.get("measurement_type", ""),
            "value": row.get("value", ""),
            "units": row.get("units", ""),
            "quality_flag": row.get("quality_flag", ""),
            "interpretation": row.get("interpretation", ""),
        }
        for row in results
    ]


def experiment_status_by_id(tables: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    statuses = {}
    for row in tables.get("Experiments", []):
        if not isinstance(row, dict):
            continue
        experiment_id = str(row.get("experiment_id", "")).strip()
        if experiment_id:
            statuses[experiment_id] = str(row.get("status", "")).strip().lower()
    return statuses


def compact_result_analysis(result_analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": result_analysis.get("summary", ""),
        "signals": result_analysis.get("signals", []),
        "limiting_metrics": result_analysis.get("limiting_metrics", []),
        "guidance": result_analysis.get("guidance", []),
        "target_profile": result_analysis.get("target_profile", ""),
    }


def suggestion_summaries(
    suggestions: list[dict[str, Any]],
    experiment_statuses: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    experiment_statuses = experiment_statuses or {}
    summaries = []
    for row in suggestions:
        proposed_experiment_id = str(row.get("proposed_experiment_id", "")).strip()
        summaries.append(
            {
                "suggestion_id": row.get("suggestion_id", ""),
                "recommendation_type": row.get("recommendation_type", ""),
                "proposed_experiment_id": proposed_experiment_id,
                "proposed_experiment_status": experiment_statuses.get(proposed_experiment_id, ""),
                "confidence": row.get("confidence", ""),
                "status": row.get("status", ""),
                "linked_evidence_ids": row.get("linked_evidence_ids", ""),
            }
        )
    return summaries


def next_actions(
    material_audit: dict[str, Any],
    results: list[dict[str, Any]],
    suggestions: list[dict[str, Any]],
    result_analysis: dict[str, Any] | None = None,
) -> list[str]:
    actions = []
    if not material_audit.get("ready_for_quantitative_suggestion", False):
        actions.extend(material_audit.get("recommendations", []))
    if not results:
        actions.append("Capture at least one normalized measurement in Results before interpreting the run.")
    analysis = result_analysis or {}
    if analysis.get("limiting_metrics"):
        first_guidance = next((str(item) for item in analysis.get("guidance", []) if str(item).strip()), "")
        if first_guidance:
            actions.append("Review result limits before accepting a follow-up: " + first_guidance)
        else:
            actions.append("Review result limits before accepting a follow-up plan.")
    if suggestions:
        actions.extend(suggestion_lifecycle_actions(suggestions))
    if not actions:
        actions.append("Notebook entry is ready for suggestion review or follow-up planning.")
    return actions


def suggestion_lifecycle_actions(suggestions: list[dict[str, Any]]) -> list[str]:
    actions = []
    by_status: dict[str, list[dict[str, Any]]] = {}
    for suggestion in suggestions:
        status = str(suggestion.get("status", "")).strip().lower()
        by_status.setdefault(status, []).append(suggestion)

    if by_status.get("draft"):
        actions.append(
            "Review draft Agent Suggestions "
            f"({format_suggestion_ids(by_status['draft'])}) and set status to accepted or rejected."
        )
    if by_status.get("accepted"):
        actions.append(
            "Materialize accepted Agent Suggestions "
            f"({format_suggestion_ids(by_status['accepted'])}) into planned Experiments, Formulations, and Results rows."
        )
    run_planned = by_status.get("run_planned", [])
    completed = [
        row
        for row in run_planned
        if str(row.get("proposed_experiment_status", "")).strip().lower() == "complete"
    ]
    if completed:
        actions.append(
            "Set run_planned Agent Suggestions "
            f"({format_suggestion_ids(completed)}) to run_complete because their planned follow-up experiments are complete."
        )
    pending = [row for row in run_planned if row not in completed]
    if pending:
        actions.append(
            "Run or update planned follow-up experiments from run_planned Agent Suggestions "
            f"({format_suggestion_ids(pending)}) before requesting a fresh recommendation."
        )
    return actions


def format_suggestion_ids(suggestions: list[dict[str, Any]], limit: int = 3) -> str:
    ids = [
        str(row.get("suggestion_id", "")).strip()
        for row in suggestions
        if str(row.get("suggestion_id", "")).strip()
    ]
    if not ids:
        return "unlabeled"
    shown = ids[:limit]
    if len(ids) > limit:
        shown.append(f"+{len(ids) - limit} more")
    return ", ".join(shown)


def summarize_daily_experiments(experiments: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "experiment_count": len(experiments),
        "observation_count": sum(int(row.get("observation_count", 0)) for row in experiments),
        "result_count": sum(int(row.get("result_count", 0)) for row in experiments),
        "open_suggestion_count": sum(len(row.get("open_suggestions", [])) for row in experiments),
        "result_limiting_metric_count": sum(len(row.get("limiting_metrics", [])) for row in experiments),
        "experiments_with_result_limits": [
            row["experiment_id"]
            for row in experiments
            if row.get("limiting_metrics")
        ],
        "experiments_with_result_signals": [
            row["experiment_id"]
            for row in experiments
            if row.get("result_signals")
        ],
        "experiments_needing_material_attention": [
            row["experiment_id"]
            for row in experiments
            if not row.get("ready_for_quantitative_suggestion", False)
        ],
    }
