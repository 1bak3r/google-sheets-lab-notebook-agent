from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .litscout import (
    build_litscout_query,
    litscout_works_to_evidence_rows,
    load_litscout_export,
    slugify,
)
from .notebook_search import search_notebook_tables
from .recommend import build_recommendation
from .search import LocalSemanticIndex
from .sheets import (
    append_rows_to_workbook,
    build_experiment_entry_from_tables,
    load_workbook_tables,
)


@dataclass(frozen=True)
class AgentRunConfig:
    experiment_ids: tuple[str, ...] = ()
    review_date: str | None = None
    context_limit: int = 5
    evidence_limit: int = 3
    force: bool = False
    litscout_export: str | None = None
    run_litscout: bool = False
    litscout_sources: str = "openalex,crossref,semantic_scholar"
    litscout_depth: str = "light"
    litscout_limit: int = 8
    artifacts_dir: str = "artifacts"


def build_agent_report(
    tables: dict[str, list[dict[str, Any]]],
    config: AgentRunConfig | None = None,
    index: LocalSemanticIndex | None = None,
) -> dict[str, Any]:
    config = config or AgentRunConfig()
    index = index or LocalSemanticIndex.from_default()
    works = load_litscout_export(config.litscout_export) if config.litscout_export else []
    runs = []

    selected_ids = selected_experiment_ids(
        tables,
        config.experiment_ids,
        review_date=config.review_date,
    )
    for experiment_id in selected_ids:
        existing_suggestions = suggestions_for_experiment(tables, experiment_id)
        if existing_suggestions and not config.force:
            runs.append(
                {
                    "experiment_id": experiment_id,
                    "status": "skipped",
                    "skip_reason": "existing_suggestion",
                    "existing_suggestion_ids": [
                        row.get("suggestion_id", "") for row in existing_suggestions if row.get("suggestion_id")
                    ],
                    "append_literature_evidence": [],
                    "append_agent_suggestions": [],
                }
            )
            continue

        entry = build_experiment_entry_from_tables(tables, experiment_id)
        query = build_litscout_query(entry)
        notebook_matches = notebook_context_matches(tables, query, experiment_id, limit=config.context_limit)
        existing_evidence = evidence_for_experiment(tables, experiment_id)
        new_evidence = []
        litscout_export_path = config.litscout_export

        if existing_evidence:
            entry["literature_evidence"] = existing_evidence
        else:
            candidate_works = works
            if config.run_litscout:
                candidate_works, litscout_export_path = run_litscout_for_entry(entry, config)
            if candidate_works:
                new_evidence = litscout_works_to_evidence_rows(
                    candidate_works,
                    experiment_id=experiment_id,
                    query=query,
                    limit=config.evidence_limit,
                )
                entry["literature_evidence"] = new_evidence

        suggestion = build_recommendation(entry, index)
        runs.append(
            {
                "experiment_id": experiment_id,
                "status": "ready",
                "litscout_query": query,
                "litscout_export": litscout_export_path or "",
                "notebook_context_matches": notebook_matches,
                "append_literature_evidence": rows_not_present(
                    new_evidence,
                    existing_rows=tables.get("Literature Evidence", []),
                    key="evidence_id",
                ),
                "append_agent_suggestions": [suggestion],
            }
        )

    return {
        "schema": "lab-notebook-agent-run.v1",
        "selection": {
            "requested_experiment_ids": list(config.experiment_ids),
            "review_date": config.review_date or "",
            "selected_experiment_ids": selected_ids,
        },
        "summary": summarize_runs(runs),
        "runs": runs,
    }


def run_workbook_agent(
    workbook_path: str | Path,
    config: AgentRunConfig | None = None,
    apply: bool = False,
    output_workbook: str | Path | None = None,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    tables = load_workbook_tables(workbook_path)
    report = build_agent_report(tables, config=config)
    if apply:
        apply_agent_report_to_workbook(workbook_path, report, output_workbook=output_workbook)
    if report_path:
        output = Path(report_path).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def apply_agent_report_to_workbook(
    workbook_path: str | Path,
    report: dict[str, Any],
    output_workbook: str | Path | None = None,
) -> Path:
    destination = Path(output_workbook).expanduser().resolve() if output_workbook else Path(workbook_path).expanduser().resolve()
    current = Path(workbook_path).expanduser().resolve()
    for run in report.get("runs", []):
        evidence_rows = run.get("append_literature_evidence", [])
        suggestion_rows = run.get("append_agent_suggestions", [])
        if evidence_rows:
            append_rows_to_workbook(current, "Literature Evidence", evidence_rows, destination)
            current = destination
        if suggestion_rows:
            append_rows_to_workbook(
                current,
                "Agent Suggestions",
                [suggestion_to_workbook_row(suggestion) for suggestion in suggestion_rows],
                destination,
            )
            current = destination
    return destination


def run_litscout_for_entry(entry: dict[str, Any], config: AgentRunConfig) -> tuple[list[dict[str, Any]], str]:
    experiment_id = str(entry.get("experiment_id", "experiment"))
    experiment_slug = slugify(experiment_id)
    session_name = f"labnotebook/{experiment_slug}"
    query = build_litscout_query(entry)
    artifacts_dir = Path(config.artifacts_dir).expanduser().resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    export_path = artifacts_dir / f"litscout-{experiment_slug}.json"
    subprocess.run(
        [
            "litscout",
            "search",
            "multi",
            query,
            "--sources",
            config.litscout_sources,
            "--depth",
            config.litscout_depth,
            "--limit",
            str(config.litscout_limit),
            "--save",
            "--session-name",
            session_name,
            "--format",
            "json",
        ],
        check=True,
    )
    subprocess.run(
        [
            "litscout",
            "sessions",
            "export",
            session_name,
            "--format",
            "json",
            "--json-array",
            "--output",
            str(export_path),
        ],
        check=True,
    )
    return load_litscout_export(export_path), str(export_path)


def selected_experiment_ids(
    tables: dict[str, list[dict[str, Any]]],
    requested_ids: tuple[str, ...],
    review_date: str | None = None,
) -> list[str]:
    if requested_ids:
        return list(requested_ids)
    if review_date:
        return selected_experiment_ids_for_date(tables, review_date)
    ids = []
    for row in tables.get("Experiments", []):
        experiment_id = str(row.get("experiment_id", "")).strip()
        status = str(row.get("status", "")).strip().lower()
        if experiment_id and status != "abandoned":
            ids.append(experiment_id)
    return ids


def selected_experiment_ids_for_date(
    tables: dict[str, list[dict[str, Any]]],
    review_date: str,
) -> list[str]:
    dated_ids = set()
    for row in tables.get("Experiments", []):
        experiment_id = str(row.get("experiment_id", "")).strip()
        status = str(row.get("status", "")).strip().lower()
        if experiment_id and status != "abandoned" and cell_date_matches(row.get("date", ""), review_date):
            dated_ids.add(experiment_id)
    for row in tables.get("Daily Log", []):
        experiment_id = str(row.get("experiment_id", "")).strip()
        if experiment_id and cell_date_matches(row.get("timestamp", ""), review_date):
            dated_ids.add(experiment_id)

    ids = []
    for row in tables.get("Experiments", []):
        experiment_id = str(row.get("experiment_id", "")).strip()
        status = str(row.get("status", "")).strip().lower()
        if experiment_id in dated_ids and status != "abandoned":
            ids.append(experiment_id)
    return ids


def cell_date_matches(value: Any, review_date: str) -> bool:
    return str(value).strip().startswith(review_date)


def suggestions_for_experiment(tables: dict[str, list[dict[str, Any]]], experiment_id: str) -> list[dict[str, Any]]:
    return [
        row
        for row in tables.get("Agent Suggestions", [])
        if str(row.get("experiment_id", "")) == experiment_id
        and str(row.get("status", "")).lower() in {"draft", "accepted", "run_planned", "run_complete"}
    ]


def evidence_for_experiment(tables: dict[str, list[dict[str, Any]]], experiment_id: str) -> list[dict[str, Any]]:
    prefix = f"LIT-{slugify(experiment_id).upper().replace('/', '-')}-"
    return [
        row
        for row in tables.get("Literature Evidence", [])
        if str(row.get("evidence_id", "")).startswith(prefix)
    ]


def rows_not_present(
    rows: list[dict[str, Any]],
    existing_rows: list[dict[str, Any]],
    key: str,
) -> list[dict[str, Any]]:
    existing = {str(row.get(key, "")) for row in existing_rows}
    return [row for row in rows if str(row.get(key, "")) not in existing]


def notebook_context_matches(
    tables: dict[str, list[dict[str, Any]]],
    query: str,
    experiment_id: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    search = search_notebook_tables(tables, query, k=max(limit * 3, limit))
    matches = []
    for result in search.get("results", []):
        if is_current_experiment_row(result, experiment_id):
            continue
        matches.append(result)
        if len(matches) >= limit:
            break
    return matches


def is_current_experiment_row(result: dict[str, Any], experiment_id: str) -> bool:
    sheet = str(result.get("sheet", ""))
    key_fields = result.get("key_fields", {}) if isinstance(result.get("key_fields"), dict) else {}
    row = result.get("row", {}) if isinstance(result.get("row"), dict) else {}
    if sheet == "Experiments" and str(key_fields.get("experiment_id", "")) == experiment_id:
        return True
    if sheet in {"Daily Log", "Formulations", "Results"} and str(row.get("experiment_id", "")) == experiment_id:
        return True
    return False


def suggestion_to_workbook_row(suggestion: dict[str, Any]) -> dict[str, Any]:
    plan = suggestion.get("proposed_experiment_plan") if isinstance(suggestion, dict) else None
    return {
        "suggestion_id": suggestion.get("suggestion_id", ""),
        "created_at": suggestion.get("created_at", ""),
        "experiment_id": suggestion.get("experiment_id", ""),
        "recommendation_type": suggestion.get("recommendation_type", ""),
        "rationale": suggestion.get("rationale", ""),
        "proposed_change": suggestion.get("proposed_change", ""),
        "expected_effect": suggestion.get("expected_effect", ""),
        "linked_evidence_ids": ",".join(suggestion.get("linked_evidence_ids", [])),
        "proposed_experiment_id": plan.get("suggested_experiment_id", "") if isinstance(plan, dict) else "",
        "proposed_plan_json": json.dumps(plan, sort_keys=True) if isinstance(plan, dict) else "",
        "safety_check": suggestion.get("safety_check", ""),
        "confidence": suggestion.get("confidence", ""),
        "status": suggestion.get("status", "draft"),
    }


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(runs),
        "ready": sum(1 for run in runs if run.get("status") == "ready"),
        "skipped": sum(1 for run in runs if run.get("status") == "skipped"),
        "evidence_rows_to_append": sum(len(run.get("append_literature_evidence", [])) for run in runs),
        "suggestion_rows_to_append": sum(len(run.get("append_agent_suggestions", [])) for run in runs),
    }
