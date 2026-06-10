from __future__ import annotations

from typing import Any

from .agent import selected_experiment_ids, suggestions_for_experiment
from .materials import audit_experiment_materials
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
    experiments = []
    for experiment_id in selected_ids:
        entry = build_experiment_entry_from_tables(tables, experiment_id)
        material_audit = audit_experiment_materials(entry)
        observations = [row for row in entry.get("observations", []) if isinstance(row, dict)]
        results = [row for row in entry.get("results", []) if isinstance(row, dict)]
        suggestions = suggestions_for_experiment(tables, experiment_id)
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
                "material_audit_summary": material_audit.get("summary", ""),
                "ready_for_quantitative_suggestion": material_audit.get("ready_for_quantitative_suggestion", False),
                "material_recommendations": material_audit.get("recommendations", []),
                "open_suggestions": suggestion_summaries(suggestions),
                "next_actions": next_actions(material_audit, results, suggestions),
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


def suggestion_summaries(suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "suggestion_id": row.get("suggestion_id", ""),
            "recommendation_type": row.get("recommendation_type", ""),
            "proposed_experiment_id": row.get("proposed_experiment_id", ""),
            "confidence": row.get("confidence", ""),
            "status": row.get("status", ""),
            "linked_evidence_ids": row.get("linked_evidence_ids", ""),
        }
        for row in suggestions
    ]


def next_actions(
    material_audit: dict[str, Any],
    results: list[dict[str, Any]],
    suggestions: list[dict[str, Any]],
) -> list[str]:
    actions = []
    if not material_audit.get("ready_for_quantitative_suggestion", False):
        actions.extend(material_audit.get("recommendations", []))
    if not results:
        actions.append("Capture at least one normalized measurement in Results before interpreting the run.")
    if suggestions:
        actions.append("Review open Agent Suggestions and set status to accepted, rejected, or run_planned.")
    if not actions:
        actions.append("Notebook entry is ready for suggestion review or follow-up planning.")
    return actions


def summarize_daily_experiments(experiments: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "experiment_count": len(experiments),
        "observation_count": sum(int(row.get("observation_count", 0)) for row in experiments),
        "result_count": sum(int(row.get("result_count", 0)) for row in experiments),
        "open_suggestion_count": sum(len(row.get("open_suggestions", [])) for row in experiments),
        "experiments_needing_material_attention": [
            row["experiment_id"]
            for row in experiments
            if not row.get("ready_for_quantitative_suggestion", False)
        ],
    }
