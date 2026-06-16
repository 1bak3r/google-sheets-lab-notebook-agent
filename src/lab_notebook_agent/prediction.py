from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .agent import AgentRunConfig, build_agent_report
from .preflight import build_experiment_preflight_report
from .search import LocalSemanticIndex


EMULSION_CURRENT_RESULT_METRICS = {
    "particle_size": "DLS particle size",
    "polydispersity": "PDI or polydispersity index",
    "conversion": "conversion percent",
    "coagulum": "coagulum mass or retained solids",
    "solids": "solids percent",
    "residual_monomer": "residual monomer percent",
}


def build_litscout_prediction_report(
    tables: dict[str, list[dict[str, Any]]],
    config: AgentRunConfig | None = None,
    index: LocalSemanticIndex | None = None,
) -> dict[str, Any]:
    """Build an auditable next-experiment prediction report from notebook + LitScout context."""
    agent_report = build_agent_report(tables, config=config, index=index)
    predictions = []
    for run in agent_report.get("runs", []):
        experiment_id = str(run.get("experiment_id", "")).strip()
        preflight = build_experiment_preflight_report(tables, experiment_id, stage="review") if experiment_id else {}
        predictions.append(prediction_from_agent_run(tables, run, preflight))
    summary = summarize_predictions(predictions)
    return {
        "schema": "lab-notebook-litscout-prediction.v1",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "selection": agent_report.get("selection", {}),
        "summary": summary,
        "agent_config": agent_report.get("agent_config", {}),
        "predictions": predictions,
        "agent_report_summary": agent_report.get("summary", {}),
    }


def prediction_from_agent_run(
    tables: dict[str, list[dict[str, Any]]],
    run: dict[str, Any],
    preflight: dict[str, Any],
) -> dict[str, Any]:
    suggestion = first_suggestion(run)
    missing_skill_set = prediction_missing_skill_set(tables, run, suggestion, preflight)
    status = prediction_status(run, suggestion, missing_skill_set)
    plan = suggestion.get("proposed_experiment_plan", {}) if suggestion else {}
    return {
        "experiment_id": run.get("experiment_id", ""),
        "status": status,
        "skip_reason": run.get("skip_reason", ""),
        "prediction": prediction_payload(suggestion, plan),
        "evidence": evidence_payload(run, suggestion),
        "inference": inference_payload(run, suggestion),
        "go_no_go": go_no_go_payload(suggestion, plan),
        "missing_skill_set": missing_skill_set,
        "preflight_status": preflight.get("status", ""),
        "preflight_summary": preflight.get("summary", {}),
    }


def first_suggestion(run: dict[str, Any]) -> dict[str, Any] | None:
    suggestions = run.get("append_agent_suggestions", [])
    if suggestions and isinstance(suggestions[0], dict):
        return suggestions[0]
    suppressed = run.get("suppressed_suggestion")
    if isinstance(suppressed, dict):
        return suppressed
    return None


def prediction_payload(suggestion: dict[str, Any] | None, plan: dict[str, Any]) -> dict[str, Any]:
    if not suggestion:
        return {}
    return {
        "suggestion_id": suggestion.get("suggestion_id", ""),
        "suggested_experiment_id": plan.get("suggested_experiment_id", ""),
        "confidence": suggestion.get("confidence", ""),
        "proposed_change": suggestion.get("proposed_change", ""),
        "expected_effect": suggestion.get("expected_effect", ""),
        "plan_objective": plan.get("objective", ""),
        "plan_hypothesis": plan.get("hypothesis", ""),
        "variables": plan.get("variables", []),
        "planned_formulation_adjustments": plan.get("planned_formulation_adjustments", []),
        "sheet_rows": plan.get("sheet_rows", {}),
    }


def evidence_payload(run: dict[str, Any], suggestion: dict[str, Any] | None) -> dict[str, Any]:
    literature_context = suggestion.get("literature_context", {}) if suggestion else {}
    return {
        "litscout_query": run.get("litscout_query", ""),
        "litscout_status": run.get("litscout_status", {}),
        "litscout_export": run.get("litscout_export", ""),
        "selected_literature_evidence_ids": run.get("selected_literature_evidence_ids", []),
        "generated_literature_evidence_rows": run.get("append_literature_evidence", []),
        "litscout_semantic_matches": run.get("litscout_semantic_matches", []),
        "supporting_findings": literature_context.get("supporting_findings", []),
        "literature_tag_counts": literature_context.get("tag_counts", {}),
        "notebook_context_matches": run.get("notebook_context_matches", []),
    }


def inference_payload(run: dict[str, Any], suggestion: dict[str, Any] | None) -> dict[str, Any]:
    if not suggestion:
        return {
            "litscout_status": run.get("litscout_status", {}),
            "skip_reason": run.get("skip_reason", ""),
        }
    return {
        "rationale": suggestion.get("rationale", ""),
        "detected_signals": suggestion.get("detected_signals", []),
        "result_analysis": suggestion.get("result_analysis", {}),
        "historical_context": suggestion.get("historical_context", {}),
        "material_audit": suggestion.get("material_audit", {}),
        "literature_guidance": suggestion.get("literature_context", {}).get("guidance", []),
    }


def go_no_go_payload(suggestion: dict[str, Any] | None, plan: dict[str, Any]) -> dict[str, Any]:
    if not suggestion:
        return {}
    return {
        "acceptance_criteria": plan.get("acceptance_criteria", []),
        "measurements_to_capture": plan.get("measurements", []),
        "prerequisites": plan.get("prerequisites", []),
        "safety_check": suggestion.get("safety_check", ""),
    }


def prediction_status(
    run: dict[str, Any],
    suggestion: dict[str, Any] | None,
    missing_skill_set: list[dict[str, Any]],
) -> str:
    if not suggestion or run.get("status") != "ready":
        return "blocked"
    if any(item.get("blocks") == "prediction" for item in missing_skill_set):
        return "blocked"
    if missing_skill_set:
        return "predicted_with_gaps"
    return "predicted"


def prediction_missing_skill_set(
    tables: dict[str, list[dict[str, Any]]],
    run: dict[str, Any],
    suggestion: dict[str, Any] | None,
    preflight: dict[str, Any],
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    if run.get("skip_reason") == "litscout_failed":
        gaps.append(
            skill_gap(
                "litscout_execution_failed",
                "error",
                "prediction",
                "LitScout search/export failed, so the agent did not create a grounded prediction.",
                run.get("litscout_status", {}).get("message", "Fix the LitScout CLI run and retry."),
                {"litscout_status": run.get("litscout_status", {})},
            )
        )
    if not suggestion:
        gaps.append(
            skill_gap(
                "suggestion_missing",
                "error",
                "prediction",
                "No next-experiment suggestion was generated for this run.",
                "Resolve the skip reason, rerun with --force if an open suggestion is intentionally being superseded, or lower the confidence floor only after review.",
                {"run_status": run.get("status", ""), "skip_reason": run.get("skip_reason", "")},
            )
        )
    selected_ids = run.get("selected_literature_evidence_ids", [])
    if suggestion and not selected_ids:
        gaps.append(
            skill_gap(
                "literature_evidence_missing",
                "error",
                "prediction",
                "The prediction has no linked LitScout or Literature Evidence rows.",
                "Run with --run-litscout, provide --litscout-export, or link reviewed Literature Evidence before accepting the prediction.",
                {"litscout_status": run.get("litscout_status", {})},
            )
        )
    if run.get("append_literature_evidence"):
        gaps.append(
            skill_gap(
                "litscout_evidence_unreviewed",
                "warning",
                "review",
                "LitScout evidence was generated in this dry-run report but is not yet reviewed or written into the notebook.",
                "Review the generated Literature Evidence rows, then apply or paste them into the sheet before treating the prediction as curated.",
                {"generated_evidence_count": len(run.get("append_literature_evidence", []))},
            )
        )
    gaps.extend(safety_check_gaps(suggestion))
    gaps.extend(preflight_gaps(preflight, selected_ids))
    gaps.extend(current_result_metric_gaps(tables, str(run.get("experiment_id", "")), suggestion))
    if suggestion:
        history = suggestion.get("historical_context", {})
        if not history.get("prior_experiment_count"):
            gaps.append(
                skill_gap(
                    "historical_benchmarks_missing",
                    "info",
                    "review",
                    "No same-process prior experiment benchmarks were available for this prediction.",
                    "Add prior completed experiment rows and Results, or treat this as a first-pass prediction with lower benchmarking confidence.",
                    {"prior_experiment_count": history.get("prior_experiment_count", 0)},
                )
            )
    return dedupe_gaps(gaps)


def safety_check_gaps(suggestion: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not suggestion:
        return []
    safety_check = str(suggestion.get("safety_check", "")).strip()
    if not safety_check:
        return [
            skill_gap(
                "safety_check_missing_or_failed",
                "error",
                "prediction",
                "The prediction has no safety check.",
                "Add a safety check that records SDS, SOP, thermal, pressure, PPE, waste, and hazard review before accepting the prediction.",
                {"safety_check": safety_check},
            )
        ]
    lowered = safety_check.lower()
    failed_terms = ("failed", "not approved", "unsafe", "do not run", "blocked")
    if any(term in lowered for term in failed_terms):
        return [
            skill_gap(
                "safety_check_missing_or_failed",
                "error",
                "prediction",
                "The prediction safety check is failed or explicitly not approved.",
                "Resolve the safety finding and record an approved safety review before accepting the prediction.",
                {"safety_check": safety_check},
            )
        ]
    approved_terms = (
        "approved",
        "safety review complete",
        "safety review completed",
        "safety review passed",
        "sds reviewed",
        "sop reviewed",
    )
    if any(term in lowered for term in approved_terms):
        return []
    return [
        skill_gap(
            "safety_review_required",
            "error",
            "prediction",
            "The prediction includes a safety reminder but no recorded approved safety review.",
            "Complete and record SDS, SOP, pressure/thermal, PPE, waste, and hazard review before accepting the prediction.",
            {"safety_check": safety_check},
        )
    ]


def preflight_gaps(preflight: dict[str, Any], selected_evidence_ids: list[str]) -> list[dict[str, Any]]:
    gaps = []
    for check in preflight.get("checks", []):
        status = str(check.get("status", "")).strip().lower()
        name = str(check.get("name", "")).strip()
        if status not in {"fail", "warn"}:
            continue
        if name == "literature_evidence" and selected_evidence_ids:
            continue
        gaps.append(
            skill_gap(
                f"{name}_missing",
                "warning" if status == "warn" else "error",
                "execution" if status == "fail" else "review",
                str(check.get("message", "")),
                " ".join(str(action) for action in check.get("actions", []) if action) or str(check.get("message", "")),
                {"check": name, "details": check.get("details", {})},
            )
        )
    return gaps


def current_result_metric_gaps(
    tables: dict[str, list[dict[str, Any]]],
    experiment_id: str,
    suggestion: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not suggestion:
        return []
    process_type = str(suggestion.get("proposed_experiment_plan", {}).get("process_type", "")).lower()
    if "emulsion" not in process_type or "polymer" not in process_type:
        return []
    present = {
        result_metric_key(row)
        for row in tables.get("Results", [])
        if str(row.get("experiment_id", "")).strip() == experiment_id
    }
    present.discard("")
    missing = [
        label
        for key, label in EMULSION_CURRENT_RESULT_METRICS.items()
        if key not in present
    ]
    if not missing:
        return []
    return [
        skill_gap(
            "result_metrics_missing",
            "warning",
            "review",
            "The current experiment lacks one or more emulsion-polymerization outcome metrics needed for a stronger prediction.",
            "Capture or backfill: " + ", ".join(missing) + ".",
            {"present_metric_keys": sorted(present), "missing_metrics": missing},
        )
    ]


def result_metric_key(row: dict[str, Any]) -> str:
    text = " ".join(
        str(row.get(field, ""))
        for field in ("measurement_type", "method", "units", "condition")
    ).lower()
    if "dls" in text or ("particle" in text and "size" in text):
        return "particle_size"
    if "polydispersity" in text or "pdi" in text:
        return "polydispersity"
    if "conversion" in text:
        return "conversion"
    if "coagulum" in text or "retained solid" in text:
        return "coagulum"
    if "solid" in text:
        return "solids"
    if "residual" in text and "monomer" in text:
        return "residual_monomer"
    return ""


def skill_gap(
    code: str,
    severity: str,
    blocks: str,
    issue: str,
    required_action: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "blocks": blocks,
        "issue": issue,
        "required_action": required_action,
        "evidence": evidence,
    }


def dedupe_gaps(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for gap in gaps:
        key = (gap.get("code"), gap.get("issue"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(gap)
    return deduped


def summarize_predictions(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    missing_count = 0
    prediction_blockers = 0
    for prediction in predictions:
        status = str(prediction.get("status", ""))
        status_counts[status] = status_counts.get(status, 0) + 1
        gaps = prediction.get("missing_skill_set", [])
        missing_count += len(gaps)
        prediction_blockers += sum(1 for gap in gaps if gap.get("blocks") == "prediction")
    return {
        "prediction_count": len(predictions),
        "status_counts": status_counts,
        "missing_skill_set_count": missing_count,
        "prediction_blocker_count": prediction_blockers,
    }
