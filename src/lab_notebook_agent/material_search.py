from __future__ import annotations

from typing import Any

from .materials import nonblank, role_specs_for_process
from .search import LocalSemanticIndex, flatten_text, tokenize


def build_process_material_search_report(
    tables: dict[str, list[dict[str, Any]]],
    process_type: str | None = None,
    experiment_id: str | None = None,
    query: str = "",
    k: int = 3,
    include_optional: bool = False,
) -> dict[str, Any]:
    process_type = str(process_type or experiment_process_type(tables, experiment_id) or "").strip()
    role_specs = role_specs_for_process(process_type.lower())
    master_reagents = [row for row in tables.get("Master Reagents", []) if isinstance(row, dict)]
    process_knowledge = [row for row in tables.get("Process Knowledge", []) if isinstance(row, dict)]
    formulation = [
        row
        for row in tables.get("Formulations", [])
        if isinstance(row, dict) and experiment_id and str(row.get("experiment_id", "")) == experiment_id
    ]
    reagent_records = master_reagent_records(master_reagents)
    knowledge_records = process_knowledge_records(process_knowledge)
    reagent_index = LocalSemanticIndex(reagent_records) if reagent_records else None
    knowledge_index = LocalSemanticIndex(knowledge_records) if knowledge_records else None

    role_results = []
    for spec in role_specs:
        if not spec.get("required") and not include_optional and spec.get("role_group") != "aqueous_phase":
            continue
        role_query = material_role_query(process_type, spec, query)
        candidates = ranked_reagent_candidates(
            spec,
            role_query,
            reagent_records,
            reagent_index,
            k=k,
        )
        knowledge_matches = ranked_process_knowledge_matches(
            spec,
            role_query,
            knowledge_records,
            knowledge_index,
            k=k,
        )
        present_formulation = formulation_rows_for_role(formulation, spec)
        role_results.append(
            {
                "role_group": spec.get("role_group", ""),
                "required": bool(spec.get("required", False)),
                "acceptable_roles": spec.get("acceptable_roles", []),
                "examples": spec.get("examples", []),
                "important_reagent_fields": spec.get("important_reagent_fields", []),
                "query": role_query,
                "present_formulation_rows": present_formulation,
                "candidate_reagents": candidates,
                "process_knowledge_matches": knowledge_matches,
                "status": role_status(spec, candidates, present_formulation),
                "actions": role_actions(spec, candidates, present_formulation, experiment_id),
            }
        )

    return {
        "schema": "lab-notebook-agent-process-material-search.v1",
        "process_type": process_type,
        "experiment_id": experiment_id or "",
        "query": query,
        "include_optional": include_optional,
        "summary": material_search_summary(role_results, master_reagents, process_knowledge),
        "roles": role_results,
    }


def experiment_process_type(tables: dict[str, list[dict[str, Any]]], experiment_id: str | None) -> str:
    if not experiment_id:
        return ""
    for row in tables.get("Experiments", []):
        if str(row.get("experiment_id", "")).strip() == experiment_id:
            return str(row.get("process_type", "")).strip()
    return ""


def master_reagent_records(master_reagents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for index, row in enumerate(master_reagents, start=2):
        record = {
            "record_id": f"Master Reagents:{row.get('reagent_id', f'row-{index}')}",
            "row_number": index,
            "row": row,
            "search_text": " ".join(
                [
                    "Master Reagents",
                    str(row.get("reagent_id", "")),
                    str(row.get("name", "")),
                    str(row.get("common_name", "")),
                    str(row.get("category", "")),
                    str(row.get("role", "")),
                    str(row.get("notes", "")),
                    str(row.get("hazards", "")),
                ]
            ),
        }
        records.append(record)
    return records


def process_knowledge_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for index, row in enumerate(rows, start=2):
        records.append(
            {
                "record_id": f"Process Knowledge:{row.get('process_type', '')}:{row.get('material_role', index)}",
                "row_number": index,
                "row": row,
                "search_text": flatten_text(row),
            }
        )
    return records


def material_role_query(process_type: str, spec: dict[str, Any], query: str) -> str:
    return " ".join(
        [
            process_type,
            str(spec.get("role_group", "")),
            " ".join(str(item) for item in spec.get("acceptable_roles", [])),
            " ".join(str(item) for item in spec.get("examples", [])),
            query,
        ]
    ).strip()


def ranked_reagent_candidates(
    spec: dict[str, Any],
    role_query: str,
    records: list[dict[str, Any]],
    index: LocalSemanticIndex | None,
    k: int,
) -> list[dict[str, Any]]:
    semantic_scores = semantic_score_map(index, role_query, k=max(len(records), k))
    scored = []
    for record in records:
        row = record["row"]
        direct_score, reasons = direct_reagent_match_score(row, spec)
        semantic_score = semantic_scores.get(record["record_id"], 0.0)
        if direct_score == 0 and semantic_score < 0.2:
            continue
        total = direct_score + semantic_score
        if total <= 0:
            continue
        important_fields = [str(field) for field in spec.get("important_reagent_fields", [])]
        missing_fields = [
            field
            for field in important_fields
            if not nonblank(row.get(field))
        ]
        scored.append(
            {
                "score": round(total, 4),
                "semantic_score": round(semantic_score, 4),
                "match_reasons": reasons or ["semantic_text_match"],
                "row_number": record["row_number"],
                "reagent_id": row.get("reagent_id", ""),
                "name": row.get("name", ""),
                "common_name": row.get("common_name", ""),
                "category": row.get("category", ""),
                "role": row.get("role", ""),
                "important_fields_complete": not missing_fields,
                "missing_important_fields": missing_fields,
            }
        )
    scored.sort(key=lambda row: row["score"], reverse=True)
    return scored[:k]


def ranked_process_knowledge_matches(
    spec: dict[str, Any],
    role_query: str,
    records: list[dict[str, Any]],
    index: LocalSemanticIndex | None,
    k: int,
) -> list[dict[str, Any]]:
    semantic_scores = semantic_score_map(index, role_query, k=max(len(records), k))
    scored = []
    acceptable = role_terms(spec)
    for record in records:
        row = record["row"]
        material_role = str(row.get("material_role", "")).lower()
        direct = 0.75 if material_role in acceptable or str(spec.get("role_group", "")).lower() in material_role else 0.0
        score = direct + semantic_scores.get(record["record_id"], 0.0)
        if score <= 0:
            continue
        scored.append(
            {
                "score": round(score, 4),
                "row_number": record["row_number"],
                "process_type": row.get("process_type", ""),
                "material_role": row.get("material_role", ""),
                "typical_examples": row.get("typical_examples", ""),
                "measured_fields": row.get("measured_fields", ""),
                "guidance": row.get("guidance", ""),
                "search_terms": row.get("search_terms", ""),
            }
        )
    scored.sort(key=lambda row: row["score"], reverse=True)
    return scored[:k]


def semantic_score_map(index: LocalSemanticIndex | None, query: str, k: int) -> dict[str, float]:
    if not index:
        return {}
    return {
        str(result.record.get("record_id", "")): result.score
        for result in index.search(query, k=k)
    }


def direct_reagent_match_score(row: dict[str, Any], spec: dict[str, Any]) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    acceptable = role_terms(spec)
    category = str(row.get("category", "")).strip().lower()
    role = str(row.get("role", "")).strip().lower()
    name = " ".join(str(row.get(field, "")) for field in ("name", "common_name", "notes")).lower()
    row_tokens = set(tokenize(" ".join([category, role, name])))
    role_tokens = set(tokenize(role))

    if category in acceptable:
        score += 1.25
        reasons.append("category_matches_role")
    if role_tokens & acceptable:
        score += 1.0
        reasons.append("role_text_matches")
    role_group = str(spec.get("role_group", "")).lower()
    if role_group and role_group in category:
        score += 0.75
        reasons.append("category_contains_role_group")
    example_tokens = set(tokenize(" ".join(str(item) for item in spec.get("examples", []))))
    overlap = row_tokens & example_tokens
    if overlap:
        score += min(0.75, 0.15 * len(overlap))
        reasons.append("example_token_overlap")
    return score, reasons


def role_terms(spec: dict[str, Any]) -> set[str]:
    terms = {str(item).strip().lower() for item in spec.get("acceptable_roles", [])}
    role_group = str(spec.get("role_group", "")).strip().lower()
    if role_group:
        terms.add(role_group)
    if role_group == "aqueous_phase":
        terms.update({"aqueous", "solvent", "water", "buffer"})
    if role_group == "crosslinker_or_chain_transfer":
        terms.update({"crosslinker", "chain_transfer_agent", "chain transfer"})
    return {term for term in terms if term}


def formulation_rows_for_role(
    formulation: list[dict[str, Any]],
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    acceptable = role_terms(spec)
    rows = []
    for row in formulation:
        target_role = str(row.get("target_role", "")).strip().lower()
        if target_role in acceptable:
            rows.append(
                {
                    "reagent_id": row.get("reagent_id", ""),
                    "target_role": row.get("target_role", ""),
                    "phase": row.get("phase", ""),
                    "mass_g": row.get("mass_g", ""),
                    "volume_mL": row.get("volume_mL", ""),
                    "moles_mmol": row.get("moles_mmol", ""),
                    "concentration": row.get("concentration", ""),
                    "wt_percent": row.get("wt_percent", ""),
                }
            )
    return rows


def role_status(
    spec: dict[str, Any],
    candidates: list[dict[str, Any]],
    present_formulation: list[dict[str, Any]],
) -> str:
    if present_formulation:
        return "present_in_formulation"
    if candidates:
        return "candidate_found"
    if spec.get("required"):
        return "missing_required_candidate"
    return "optional_no_candidate"


def role_actions(
    spec: dict[str, Any],
    candidates: list[dict[str, Any]],
    present_formulation: list[dict[str, Any]],
    experiment_id: str | None,
) -> list[str]:
    actions = []
    role_group = str(spec.get("role_group", "role"))
    if not candidates and spec.get("required"):
        actions.append(f"Add or scaffold a Master Reagents row for the required {role_group} role.")
    if not candidates and not spec.get("required"):
        actions.append(f"No Master Reagents candidate found for {role_group}; add one only if this experiment needs that role.")
    if candidates and experiment_id and not present_formulation:
        actions.append(
            f"Add a Formulations row for {experiment_id} using a reviewed {role_group} candidate."
        )
    if candidates:
        incomplete = [
            row
            for row in candidates
            if not row.get("important_fields_complete", True)
        ]
        if incomplete:
            fields = sorted(
                {
                    field
                    for row in incomplete
                    for field in row.get("missing_important_fields", [])
                }
            )
            actions.append(
                "Complete Master Reagents fields for top candidates: " + ", ".join(fields) + "."
            )
    if not actions:
        actions.append(f"Review candidate {role_group} rows before using them in a formulation.")
    return actions


def material_search_summary(
    role_results: list[dict[str, Any]],
    master_reagents: list[dict[str, Any]],
    process_knowledge: list[dict[str, Any]],
) -> dict[str, Any]:
    required_roles = [row for row in role_results if row.get("required")]
    missing_required = [
        row.get("role_group", "")
        for row in required_roles
        if row.get("status") == "missing_required_candidate"
    ]
    return {
        "role_group_count": len(role_results),
        "required_role_group_count": len(required_roles),
        "required_roles_with_candidates": sum(1 for row in required_roles if row.get("candidate_reagents")),
        "required_roles_missing_candidates": missing_required,
        "roles_present_in_formulation": [
            row.get("role_group", "")
            for row in role_results
            if row.get("present_formulation_rows")
        ],
        "master_reagent_records_searched": len(master_reagents),
        "process_knowledge_records_searched": len(process_knowledge),
    }
