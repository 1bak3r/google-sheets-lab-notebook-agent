from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .agent import cell_date_matches
from .planning import result_row_key
from .sheets import append_rows_to_workbook


MEASUREMENT_FIELDS: dict[str, dict[str, str]] = {
    "temperature_C": {
        "measurement_type": "temperature",
        "units": "C",
        "method": "Daily Log structured field",
    },
    "rpm": {
        "measurement_type": "agitation speed",
        "units": "rpm",
        "method": "Daily Log structured field",
    },
    "pH": {
        "measurement_type": "pH",
        "units": "",
        "method": "Daily Log structured field",
    },
    "solids_percent": {
        "measurement_type": "solids percent",
        "units": "%",
        "method": "Daily Log structured field",
    },
    "particle_size_nm": {
        "measurement_type": "DLS particle size",
        "units": "nm",
        "method": "Daily Log structured field",
    },
    "conversion_percent": {
        "measurement_type": "conversion",
        "units": "%",
        "method": "Daily Log structured field",
    },
    "viscosity_cP": {
        "measurement_type": "viscosity",
        "units": "cP",
        "method": "Daily Log structured field",
    },
}


TEXT_MEASUREMENT_PATTERNS: tuple[dict[str, Any], ...] = (
    {
        "field": "temperature_C",
        "measurement_type": "temperature",
        "units": "C",
        "method": "Daily Log observation text",
        "patterns": (
            r"\b(?:temp(?:erature)?|reactor temp(?:erature)?)\s*(?:=|:|was|at|about|~)?\s*(-?\d+(?:\.\d+)?)\s*(?:deg\s*C|degrees?\s*C|C\b)",
        ),
    },
    {
        "field": "rpm",
        "measurement_type": "agitation speed",
        "units": "rpm",
        "method": "Daily Log observation text",
        "patterns": (
            r"\b(\d+(?:\.\d+)?)\s*rpm\b",
            r"\b(?:agitation|stirring|stir rate)\s*(?:=|:|was|at|about|~)?\s*(\d+(?:\.\d+)?)\s*(?:rpm)?\b",
        ),
    },
    {
        "field": "pH",
        "measurement_type": "pH",
        "units": "",
        "method": "Daily Log observation text",
        "patterns": (
            r"\bpH\s*(?:=|:|was|at|about|~)?\s*(\d+(?:\.\d+)?)\b",
        ),
    },
    {
        "field": "solids_percent",
        "measurement_type": "solids percent",
        "units": "%",
        "method": "Daily Log observation text",
        "patterns": (
            r"\b(?:solids|solids content)\s*(?:=|:|was|at|about|~)?\s*(\d+(?:\.\d+)?)\s*%",
        ),
    },
    {
        "field": "particle_size_nm",
        "measurement_type": "DLS particle size",
        "units": "nm",
        "method": "Daily Log observation text",
        "patterns": (
            r"\b(?:particle size|DLS|diameter)\s*(?:=|:|was|at|about|~)?\s*(\d+(?:\.\d+)?)\s*nm\b",
        ),
    },
    {
        "field": "conversion_percent",
        "measurement_type": "conversion",
        "units": "%",
        "method": "Daily Log observation text",
        "patterns": (
            r"\b(?:conversion|conv(?:ersion)?)\s*(?:=|:|was|at|about|~)?\s*(\d+(?:\.\d+)?)\s*%",
        ),
    },
    {
        "field": "viscosity_cP",
        "measurement_type": "viscosity",
        "units": "cP",
        "method": "Daily Log observation text",
        "patterns": (
            r"\b(?:viscosity|visc)\s*(?:=|:|was|at|about|~)?\s*(\d+(?:\.\d+)?)\s*(?:cP|centipoise)\b",
        ),
    },
    {
        "field": "coagulum_mass_g",
        "measurement_type": "coagulum mass",
        "units": "g",
        "method": "Daily Log observation text",
        "patterns": (
            r"\b(?:coagulum|coagulate|grit)\s*(?:mass|weight)?\s*(?:=|:|was|at|about|~)?\s*(\d+(?:\.\d+)?)\s*g\b",
        ),
    },
)


def build_daily_log_results_report(
    tables: dict[str, list[dict[str, Any]]],
    experiment_ids: tuple[str, ...] = (),
    review_date: str | None = None,
) -> dict[str, Any]:
    selected_ids = {str(experiment_id) for experiment_id in experiment_ids if str(experiment_id).strip()}
    existing_results = [
        row
        for row in tables.get("Results", [])
        if isinstance(row, dict)
    ]
    existing_keys = {result_row_key(row) for row in existing_results}
    runs = []

    for row_number, log_row in enumerate(tables.get("Daily Log", []), start=2):
        if not isinstance(log_row, dict):
            continue
        experiment_id = str(log_row.get("experiment_id", "")).strip()
        timestamp = str(log_row.get("timestamp", "")).strip()
        if selected_ids and experiment_id not in selected_ids:
            continue
        if review_date and not cell_date_matches(timestamp, review_date):
            continue

        result_rows, skipped = result_rows_from_daily_log_row(
            log_row,
            row_number=row_number,
            existing_results=existing_results,
            existing_keys=existing_keys,
        )
        for result_row in result_rows:
            existing_results.append(result_row)
            existing_keys.add(result_row_key(result_row))

        status = "ready" if result_rows else "skipped"
        skip_reason = "" if result_rows else ("no_measurements_found" if not skipped else "measurements_already_present")
        runs.append(
            {
                "experiment_id": experiment_id,
                "daily_log_row_number": row_number,
                "timestamp": timestamp,
                "status": status,
                "skip_reason": skip_reason,
                "append_results": result_rows,
                "skipped_measurements": skipped,
            }
        )

    return {
        "schema": "lab-notebook-agent-daily-log-results.v1",
        "selection": {
            "requested_experiment_ids": list(experiment_ids),
            "review_date": review_date or "",
        },
        "summary": summarize_runs(runs),
        "runs": runs,
    }


def result_rows_from_daily_log_row(
    log_row: dict[str, Any],
    row_number: int,
    existing_results: list[dict[str, Any]],
    existing_keys: set[tuple[str, str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = []
    skipped = []
    local_keys = set(existing_keys)
    for field, spec in MEASUREMENT_FIELDS.items():
        value = log_row.get(field, "")
        if not nonblank(value):
            continue
        result_row = daily_log_measurement_result_row(log_row, field, spec)
        row_key = result_row_key(result_row)
        if row_key in local_keys or matching_result_value_exists(result_row, existing_results + rows):
            skipped.append(
                {
                    "daily_log_row_number": row_number,
                    "field": field,
                    "measurement_type": result_row["measurement_type"],
                    "value": result_row["value"],
                    "units": result_row["units"],
                    "skip_reason": "matching_result_already_exists",
                }
            )
            continue
        rows.append(result_row)
        local_keys.add(row_key)
    for field, spec, value in measurements_from_observation_text(log_row):
        result_row = daily_log_measurement_result_row(log_row, field, spec, value=value)
        row_key = result_row_key(result_row)
        if row_key in local_keys or matching_result_value_exists(result_row, existing_results + rows):
            skipped.append(
                {
                    "daily_log_row_number": row_number,
                    "field": field,
                    "measurement_type": result_row["measurement_type"],
                    "value": result_row["value"],
                    "units": result_row["units"],
                    "skip_reason": "matching_result_already_exists",
                }
            )
            continue
        rows.append(result_row)
        local_keys.add(row_key)
    return rows, skipped


def daily_log_measurement_result_row(
    log_row: dict[str, Any],
    field: str,
    spec: dict[str, str],
    value: Any | None = None,
) -> dict[str, Any]:
    experiment_id = str(log_row.get("experiment_id", "")).strip()
    timestamp = str(log_row.get("timestamp", "")).strip()
    process_stage = str(log_row.get("process_stage", "")).strip()
    sample_id = f"{experiment_id}-DL-{compact_token(timestamp)}-{compact_token(field)}"
    condition_parts = [part for part in [process_stage, timestamp] if part]
    return {
        "experiment_id": experiment_id,
        "sample_id": sample_id,
        "measurement_type": spec["measurement_type"],
        "method": spec["method"],
        "value": log_row.get(field, "") if value is None else value,
        "units": spec["units"],
        "condition": " | ".join(condition_parts),
        "replicate": "",
        "quality_flag": "observed",
        "interpretation": f"Normalized from {spec['method']} ({field}).",
    }


def measurements_from_observation_text(log_row: dict[str, Any]) -> list[tuple[str, dict[str, str], str]]:
    observation = str(log_row.get("observation", "") or "")
    if not observation.strip():
        return []
    measurements = []
    seen_fields = {
        field
        for field in MEASUREMENT_FIELDS
        if nonblank(log_row.get(field, ""))
    }
    for text_spec in TEXT_MEASUREMENT_PATTERNS:
        field = str(text_spec["field"])
        if field in seen_fields:
            continue
        value = first_pattern_value(observation, text_spec.get("patterns", ()))
        if value is None:
            continue
        spec = {
            "measurement_type": str(text_spec["measurement_type"]),
            "units": str(text_spec["units"]),
            "method": str(text_spec["method"]),
        }
        measurements.append((field, spec, value))
        seen_fields.add(field)
    return measurements


def first_pattern_value(text: str, patterns: Any) -> str | None:
    for pattern in patterns or ():
        match = re.search(str(pattern), text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def matching_result_value_exists(row: dict[str, Any], existing_results: list[dict[str, Any]]) -> bool:
    for existing in existing_results:
        if str(existing.get("experiment_id", "")).strip() != str(row.get("experiment_id", "")).strip():
            continue
        if str(existing.get("measurement_type", "")).strip().lower() != str(row.get("measurement_type", "")).strip().lower():
            continue
        if str(existing.get("value", "")).strip() != str(row.get("value", "")).strip():
            continue
        if str(existing.get("units", "")).strip().lower() != str(row.get("units", "")).strip().lower():
            continue
        return True
    return False


def apply_daily_log_results_report_to_workbook(
    workbook_path: str | Path,
    report: dict[str, Any],
    output_workbook: str | Path | None = None,
) -> Path:
    destination = Path(output_workbook).expanduser().resolve() if output_workbook else Path(workbook_path).expanduser().resolve()
    current = Path(workbook_path).expanduser().resolve()
    for run in report.get("runs", []):
        result_rows = run.get("append_results", [])
        if result_rows:
            append_rows_to_workbook(current, "Results", result_rows, destination)
            current = destination
    return destination


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "daily_log_rows_considered": len(runs),
        "ready": sum(1 for run in runs if run.get("status") == "ready"),
        "skipped": sum(1 for run in runs if run.get("status") == "skipped"),
        "result_rows_to_append": sum(len(run.get("append_results", [])) for run in runs),
        "measurements_skipped": sum(len(run.get("skipped_measurements", [])) for run in runs),
    }


def compact_token(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "row"
    compact = re.sub(r"[^A-Za-z0-9]+", "", text)
    return compact[:32] or "row"


def nonblank(value: Any) -> bool:
    return value is not None and str(value).strip() != ""
