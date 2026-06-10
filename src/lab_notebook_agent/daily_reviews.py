from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .sheets import append_rows_to_workbook


def daily_review_row_from_run(run: dict[str, Any]) -> dict[str, Any]:
    review_date = str(run.get("review_date", "")).strip()
    selected_ids = [
        str(experiment_id)
        for experiment_id in run.get("selection", {}).get("selected_experiment_ids", [])
        if str(experiment_id).strip()
    ]
    summary = run.get("summary", {}) if isinstance(run.get("summary"), dict) else {}
    next_actions = daily_review_next_actions(run)
    return {
        "review_id": daily_review_id(review_date, selected_ids),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "review_date": review_date,
        "selected_experiment_ids": ",".join(selected_ids),
        "experiment_count": summary.get("experiment_count", 0),
        "observation_count": summary.get("observation_count", 0),
        "result_count": summary.get("result_count", 0),
        "normalized_result_rows_to_append": summary.get("normalized_result_rows_to_append", 0),
        "evidence_rows_to_append": summary.get("evidence_rows_to_append", 0),
        "suggestion_rows_to_append": summary.get("suggestion_rows_to_append", 0),
        "preflight_fail_count": summary.get("preflight_fail_count", 0),
        "preflight_warn_count": summary.get("preflight_warn_count", 0),
        "apply_request_count": summary.get("apply_request_count", ""),
        "status": daily_review_status(summary),
        "summary": daily_review_summary_text(summary),
        "next_actions_json": json.dumps(next_actions, sort_keys=True),
    }


def apply_daily_review_rows_to_workbook(
    workbook_path: str | Path,
    rows: list[dict[str, Any]],
    output_workbook: str | Path | None = None,
) -> Path:
    if not rows:
        return Path(output_workbook or workbook_path).expanduser().resolve()
    return append_rows_to_workbook(workbook_path, "Daily Reviews", rows, output_workbook)


def daily_review_id(review_date: str, selected_ids: list[str]) -> str:
    suffix = "-".join(compact_token(experiment_id) for experiment_id in selected_ids) or "all"
    return f"DRV-{compact_token(review_date) or 'undated'}-{suffix}"


def daily_review_status(summary: dict[str, Any]) -> str:
    if int(summary.get("preflight_fail_count", 0) or 0) > 0:
        return "needs_attention"
    pending_rows = sum(
        int(summary.get(key, 0) or 0)
        for key in (
            "normalized_result_rows_to_append",
            "evidence_rows_to_append",
            "suggestion_rows_to_append",
        )
    )
    if pending_rows:
        return "ready_to_apply"
    if int(summary.get("preflight_warn_count", 0) or 0) > 0:
        return "ready_with_warnings"
    return "no_action"


def daily_review_summary_text(summary: dict[str, Any]) -> str:
    return (
        f"{summary.get('experiment_count', 0)} experiments; "
        f"{summary.get('normalized_result_rows_to_append', 0)} normalized Results rows; "
        f"{summary.get('evidence_rows_to_append', 0)} evidence rows; "
        f"{summary.get('suggestion_rows_to_append', 0)} suggestion rows; "
        f"{summary.get('preflight_fail_count', 0)} preflight failures."
    )


def daily_review_next_actions(run: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    summary = run.get("summary", {}) if isinstance(run.get("summary"), dict) else {}
    if int(summary.get("normalized_result_rows_to_append", 0) or 0):
        actions.append("Apply or review normalized Daily Log measurements in Results.")
    if int(summary.get("evidence_rows_to_append", 0) or 0):
        actions.append("Review appended Literature Evidence rows before relying on them.")
    if int(summary.get("suggestion_rows_to_append", 0) or 0):
        actions.append("Review draft Agent Suggestions and set accepted or rejected status.")
    for review in run.get("experiment_reviews", []) or []:
        if not isinstance(review, dict):
            continue
        preflight = review.get("preflight", {}) if isinstance(review.get("preflight"), dict) else {}
        for action in preflight.get("next_actions", []) or []:
            if action and action not in actions:
                actions.append(str(action))
    if not actions:
        actions.append("No notebook write actions were generated for this daily run.")
    return actions


def compact_token(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return re.sub(r"[^A-Za-z0-9]+", "", text)[:48]
