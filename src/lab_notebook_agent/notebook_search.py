from __future__ import annotations

from typing import Any

from .search import LocalSemanticIndex


DEFAULT_SEARCH_SHEETS = (
    "Master Reagents",
    "Experiments",
    "Daily Log",
    "Formulations",
    "Results",
    "Literature Evidence",
    "Agent Suggestions",
    "Daily Reviews",
    "Process Knowledge",
)

KEY_FIELDS_BY_SHEET = {
    "Master Reagents": ("reagent_id", "name", "common_name", "category", "role"),
    "Experiments": ("experiment_id", "date", "process_type", "objective", "status"),
    "Daily Log": ("experiment_id", "timestamp", "process_stage", "issue_tags"),
    "Formulations": ("experiment_id", "reagent_id", "phase", "target_role"),
    "Results": ("experiment_id", "sample_id", "measurement_type", "value", "units"),
    "Literature Evidence": ("evidence_id", "source", "title", "relevance_tags"),
    "Agent Suggestions": ("suggestion_id", "experiment_id", "recommendation_type", "status"),
    "Daily Reviews": ("review_id", "review_date", "selected_experiment_ids", "status"),
    "Process Knowledge": ("process_type", "material_role", "typical_examples"),
}


def search_notebook_tables(
    tables: dict[str, list[dict[str, Any]]],
    query: str,
    k: int = 10,
    sheets: tuple[str, ...] = (),
) -> dict[str, Any]:
    records = build_notebook_search_records(tables, sheets=sheets)
    results = LocalSemanticIndex(records).search(query, k=k)
    return {
        "schema": "lab-notebook-agent-notebook-search.v1",
        "query": query,
        "searched_sheets": list(sheets or DEFAULT_SEARCH_SHEETS),
        "summary": {
            "records_indexed": len(records),
            "results_returned": len(results),
        },
        "results": [
            {
                "score": round(result.score, 4),
                "sheet": result.record["sheet"],
                "row_number": result.record["row_number"],
                "record_id": result.record["record_id"],
                "label": result.record["label"],
                "key_fields": result.record["key_fields"],
                "row": result.record["row"],
            }
            for result in results
        ],
    }


def build_notebook_search_records(
    tables: dict[str, list[dict[str, Any]]],
    sheets: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    selected_sheets = sheets or DEFAULT_SEARCH_SHEETS
    records = []
    for sheet_name in selected_sheets:
        for row_index, row in enumerate(tables.get(sheet_name, []), start=2):
            if not row_has_content(row):
                continue
            key_fields = key_fields_for_row(sheet_name, row)
            records.append(
                {
                    "record_id": record_id(sheet_name, row_index, key_fields),
                    "sheet": sheet_name,
                    "row_number": row_index,
                    "label": row_label(sheet_name, row, key_fields),
                    "key_fields": key_fields,
                    "row": compact_row(row),
                    "search_text": search_text(sheet_name, row, key_fields),
                }
            )
    return records


def row_has_content(row: dict[str, Any]) -> bool:
    return any(str(value).strip() for value in row.values() if value is not None)


def key_fields_for_row(sheet_name: str, row: dict[str, Any]) -> dict[str, Any]:
    fields = KEY_FIELDS_BY_SHEET.get(sheet_name, ())
    return {
        field: row.get(field, "")
        for field in fields
        if str(row.get(field, "")).strip()
    }


def record_id(sheet_name: str, row_index: int, key_fields: dict[str, Any]) -> str:
    for field in ("reagent_id", "experiment_id", "evidence_id", "suggestion_id", "sample_id"):
        if key_fields.get(field):
            return f"{sheet_name}:{key_fields[field]}"
    return f"{sheet_name}:row-{row_index}"


def row_label(sheet_name: str, row: dict[str, Any], key_fields: dict[str, Any]) -> str:
    if sheet_name == "Master Reagents":
        return " ".join(str(key_fields.get(field, "")) for field in ("reagent_id", "name", "common_name")).strip()
    if sheet_name == "Experiments":
        return " ".join(str(key_fields.get(field, "")) for field in ("experiment_id", "process_type", "objective")).strip()
    if sheet_name == "Daily Log":
        return " ".join(str(key_fields.get(field, "")) for field in ("experiment_id", "timestamp", "issue_tags")).strip()
    if sheet_name == "Results":
        return " ".join(str(key_fields.get(field, "")) for field in ("experiment_id", "measurement_type", "value", "units")).strip()
    if sheet_name == "Literature Evidence":
        return " ".join(str(key_fields.get(field, "")) for field in ("evidence_id", "title")).strip()
    if sheet_name == "Daily Reviews":
        return " ".join(str(key_fields.get(field, "")) for field in ("review_id", "review_date", "status")).strip()
    return " ".join(str(value) for value in key_fields.values()).strip() or f"{sheet_name} row"


def compact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if str(value).strip()
    }


def search_text(sheet_name: str, row: dict[str, Any], key_fields: dict[str, Any]) -> str:
    parts = [sheet_name]
    parts.extend(str(value) for value in key_fields.values())
    parts.extend(f"{key} {value}" for key, value in compact_row(row).items())
    return " ".join(parts)
