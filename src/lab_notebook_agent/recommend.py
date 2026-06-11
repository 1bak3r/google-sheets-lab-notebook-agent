from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .litscout import build_litscout_commands, build_litscout_query
from .materials import audit_experiment_materials
from .result_analysis import build_result_analysis
from .search import LocalSemanticIndex, SearchResult, flatten_text


def load_entry(path: str | Path) -> dict[str, Any]:
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Experiment entry must be a JSON object.")
    return data


def build_recommendation(entry: dict[str, Any], index: LocalSemanticIndex | None = None) -> dict[str, Any]:
    index = index or LocalSemanticIndex.from_default()
    query = entry_query(entry)
    matches = index.search(query, k=4)
    signals = extract_signals(entry)
    result_analysis = build_result_analysis(entry)
    signals.update(str(signal) for signal in result_analysis.get("signals", []) if str(signal).strip())
    material_audit = audit_experiment_materials(entry)
    experiment_id = str(entry.get("experiment_id", "unassigned"))
    process_type = str(entry.get("process_type", "")).lower()
    literature = entry.get("literature_evidence", []) or []
    literature_context = build_literature_context(literature)
    linked_evidence_ids = literature_context["evidence_ids"]
    historical_context = entry.get("historical_context") if isinstance(entry.get("historical_context"), dict) else {}

    if "emulsion" in process_type and "polymer" in process_type:
        proposal = emulsion_polymerization_next_experiment(entry, signals, matches, literature_context)
    else:
        proposal = generic_next_experiment(entry, signals, matches, literature_context)

    confidence = "medium" if matches and signals else "low"
    if "coagulum" in signals or "particle_size_high" in signals:
        confidence = "medium"
    rationale = proposal["rationale"]
    if result_analysis.get("summary"):
        rationale = f"{rationale} Result analysis: {result_analysis['summary']}"
    for guidance in result_analysis.get("guidance", [])[:2]:
        rationale = f"{rationale} Result guidance: {guidance}"
    if material_audit["summary"]:
        rationale = f"{rationale} Material audit: {material_audit['summary']}"
    if historical_context.get("guidance"):
        rationale = f"{rationale} Notebook history: {' '.join(historical_context['guidance'][:2])}"
    if linked_evidence_ids:
        rationale = (
            f"{rationale} Literature Evidence rows {', '.join(linked_evidence_ids[:5])} "
            "are linked for human review before execution."
        )
        if literature_context["summary"]:
            rationale = f"{rationale} {literature_context['summary']}"
        confidence = "medium"
    proposed_plan = build_proposed_experiment_plan(
        entry,
        signals=signals,
        material_audit=material_audit,
        result_analysis=result_analysis,
        linked_evidence_ids=linked_evidence_ids,
        literature_context=literature_context,
        historical_context=historical_context,
    )

    return {
        "suggestion_id": f"SUG-{experiment_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "experiment_id": experiment_id,
        "recommendation_type": "next_experiment",
        "rationale": rationale,
        "proposed_change": proposal["proposed_change"],
        "expected_effect": proposal["expected_effect"],
        "linked_evidence_ids": linked_evidence_ids,
        "safety_check": (
            "Human review required. Confirm SDS, SOP, pressure/thermal limits, "
            "inhibitor removal assumptions, and waste handling before running."
        ),
        "confidence": confidence,
        "status": "draft",
        "detected_signals": sorted(signals),
        "result_analysis": result_analysis,
        "material_audit": material_audit,
        "historical_context": historical_context,
        "literature_context": literature_context,
        "proposed_experiment_plan": proposed_plan,
        "knowledge_matches": [
            {
                "id": result.record.get("id"),
                "process_type": result.record.get("process_type"),
                "score": round(result.score, 4),
                "summary": result.record.get("summary"),
            }
            for result in matches
        ],
        "litscout": {
            "query": build_litscout_query(entry, matches),
            "commands": build_litscout_commands(entry, matches, **litscout_command_kwargs(entry)),
        },
    }


def litscout_command_kwargs(entry: dict[str, Any]) -> dict[str, Any]:
    config = entry.get("litscout_config", {}) if isinstance(entry.get("litscout_config"), dict) else {}
    kwargs = {}
    if config.get("artifacts_dir"):
        kwargs["artifacts_dir"] = config["artifacts_dir"]
    if config.get("sources"):
        kwargs["sources"] = config["sources"]
    if config.get("depth"):
        kwargs["depth"] = config["depth"]
    if config.get("limit") not in ("", None):
        kwargs["limit"] = config["limit"]
    return kwargs


def entry_query(entry: dict[str, Any]) -> str:
    return " ".join(
        [
            str(entry.get("process_type", "")),
            str(entry.get("objective", "")),
            str(entry.get("hypothesis", "")),
            flatten_text(entry.get("observations", "")),
            flatten_text(entry.get("results", "")),
            flatten_text(entry.get("formulation", "")),
        ]
    )


def extract_signals(entry: dict[str, Any]) -> set[str]:
    text = entry_query(entry).lower()
    signals: set[str] = set()
    if "coagulum" in text or "coagulated" in text or "phase separation" in text:
        signals.add("coagulum")
    if "grit" in text or "precipitate" in text:
        signals.add("instability")
    if "low conversion" in text:
        signals.add("low_conversion")

    for observation in entry.get("observations", []) or []:
        if isinstance(observation, dict):
            for tag in str(observation.get("issue_tags", "")).split(","):
                tag = tag.strip().lower()
                if tag:
                    signals.add(tag)
            particle_size = coerce_float(observation.get("particle_size_nm"))
            if particle_size and particle_size > 350:
                signals.add("particle_size_high")
            conversion = coerce_float(observation.get("conversion_percent"))
            if conversion is not None and conversion < 85:
                signals.add("low_conversion")

    for result in entry.get("results", []) or []:
        if isinstance(result, dict):
            measurement = str(result.get("measurement_type", "")).lower()
            value = coerce_float(result.get("value"))
            if value and ("particle" in measurement or "dls" in measurement) and value > 350:
                signals.add("particle_size_high")
            if value is not None and "conversion" in measurement and value < 85:
                signals.add("low_conversion")
    return signals


def coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_literature_context(literature: Any) -> dict[str, Any]:
    rows = [row for row in literature or [] if isinstance(row, dict)]
    tag_counts: dict[str, int] = {}
    evidence_ids = []
    supporting_findings = []
    for row in rows:
        evidence_id = str(row.get("evidence_id", "")).strip()
        if evidence_id:
            evidence_ids.append(evidence_id)
        tags = literature_tags_for_row(row)
        for tag in tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        supporting_findings.append(
            {
                "evidence_id": evidence_id,
                "title": short_text(row.get("title", ""), limit=140),
                "finding": short_text(row.get("finding", ""), limit=240),
                "relevance_tags": tags,
                "confidence": row.get("confidence", ""),
            }
        )
    ordered_tags = sorted(tag_counts, key=lambda tag: (-tag_counts[tag], tag))
    return {
        "evidence_count": len(rows),
        "evidence_ids": evidence_ids,
        "relevance_tags": ordered_tags,
        "tag_counts": {tag: tag_counts[tag] for tag in ordered_tags},
        "guidance": literature_guidance(ordered_tags),
        "supporting_findings": supporting_findings[:5],
        "summary": literature_context_summary(tag_counts),
    }


def literature_tags_for_row(row: dict[str, Any]) -> list[str]:
    tags = {
        tag.strip()
        for tag in str(row.get("relevance_tags", "")).replace(";", ",").split(",")
        if tag.strip()
    }
    if tags:
        return sorted(tags)
    text = " ".join(
        str(row.get(field, ""))
        for field in ("title", "finding", "query", "notes")
    ).lower()
    inferred = {
        "surfactant": ("surfactant", "sds", "anionic", "nonionic", "ionic"),
        "particle_size": ("particle size", "particles", "dls", "diameter", "nucleation"),
        "stability": ("stability", "coagulum", "coagulation", "colloidal", "latex"),
        "initiator": ("initiator", "persulfate", "radical", "aps"),
        "monomer": ("monomer", "acrylate", "methacrylate"),
        "feed": ("feed", "semibatch", "semi-batch", "starved"),
    }
    return sorted(tag for tag, terms in inferred.items() if any(term in text for term in terms))


def literature_guidance(tags: list[str]) -> list[str]:
    guidance = []
    tag_set = set(tags)
    if {"surfactant", "particle_size"} <= tag_set or {"surfactant", "stability"} <= tag_set:
        guidance.append("Use linked evidence to prioritize surfactant active basis or surfactant package as a controlled factor.")
    if "feed" in tag_set:
        guidance.append("Keep monomer feed profile explicit because linked evidence points to feed/nucleation sensitivity.")
    if "initiator" in tag_set:
        guidance.append("Track initiator freshness, radical flux, and chase strategy as possible process-health factors.")
    if "monomer" in tag_set:
        guidance.append("Keep monomer identity fixed unless the literature review explicitly supports a chemistry change.")
    return guidance


def literature_context_summary(tag_counts: dict[str, int]) -> str:
    if not tag_counts:
        return ""
    parts = [
        f"{tag} ({count})"
        for tag, count in sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    ]
    return "Linked literature tags emphasize " + ", ".join(parts) + "."


def short_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 0)].rstrip() + "..."


def emulsion_polymerization_next_experiment(
    entry: dict[str, Any],
    signals: set[str],
    matches: list[SearchResult],
    literature_context: dict[str, Any] | None = None,
) -> dict[str, str]:
    focus = emulsion_followup_focus(signals)
    base = focus["proposal_base"]
    changes = [
        "Create two or three conditions around the current formulation rather than changing every factor.",
        "Record surfactant identity, surfactant active mass, initiator feed, monomer feed rate, pH, temperature, solids, particle size, conversion, and coagulum mass.",
    ]
    rationale_bits = [
        "The process-knowledge match indicates emulsion polymerization outcomes are strongly tied to surfactant package, radical flux, feed profile, and particle-size measurements."
    ]
    expected = [
        "The next run should make particle-size and stability changes attributable to one formulation axis."
    ]

    if "particle_size_high" in signals:
        changes.append(
            "Add a particle-size arm that modestly increases effective surfactant level or slows monomer feed while leaving monomer composition fixed."
        )
        rationale_bits.append("The entry reports particle size above the 200-350 nm scaffold target window.")
        expected.append("Particle size should shift downward or reveal whether surfactant/feed is not the controlling factor.")
    if "coagulum" in signals or "instability" in signals:
        changes.append(
            "Add a stability arm that uses the same total surfactant active mass but compares ionic-only versus mixed ionic/nonionic surfactant package."
        )
        rationale_bits.append("The entry reports coagulum or visible instability, so latex stabilization should be isolated before changing monomers.")
        expected.append("Coagulum mass should decrease if colloidal stabilization is limiting the current recipe.")
    if "low_conversion" in signals:
        changes.append(
            "Add an initiator/process-health check: verify initiator freshness, hold temperature, purge quality, and consider a chase feed only after the baseline is reproduced."
        )
        rationale_bits.append("The entry suggests low conversion, which can confound particle-size and stability conclusions.")
        expected.append("Conversion should improve or identify oxygen inhibition, thermal drift, or initiator decomposition as a constraint.")

    if len(changes) == 2:
        changes.append(
            "Use a small DOE with surfactant level and feed duration as the first two factors because these are actionable and measurable in the current sheet schema."
        )
    for guidance in (literature_context or {}).get("guidance", [])[:2]:
        rationale_bits.append(f"Literature guidance: {guidance}")
    material_audit = audit_experiment_materials(entry)
    if material_audit["missing_required_role_groups"] or material_audit["quantity_gaps"]:
        changes.append(
            "Before running the follow-up, complete the material scaffold: "
            + " ".join(material_audit["recommendations"])
        )

    if matches:
        top = matches[0].record.get("summary")
        if top:
            rationale_bits.append(f"Top local knowledge match: {top}")

    return {
        "rationale": " ".join(rationale_bits),
        "proposed_change": base + " " + " ".join(changes),
        "expected_effect": " ".join(expected),
    }


def generic_next_experiment(
    entry: dict[str, Any],
    signals: set[str],
    matches: list[SearchResult],
    literature_context: dict[str, Any] | None = None,
) -> dict[str, str]:
    objective = entry.get("objective", "the current objective")
    match_text = matches[0].record.get("summary") if matches else "No strong process match was found."
    guidance = " ".join((literature_context or {}).get("guidance", [])[:1])
    return {
        "rationale": f"Use the current result to isolate one variable related to {objective}. {match_text} {guidance}".strip(),
        "proposed_change": (
            "Plan one follow-up experiment with a single intentional variable, "
            "hold all other formulation and process fields constant, and add "
            "missing measurements to the Results tab."
        ),
        "expected_effect": "The result should be easier to attribute to the selected variable.",
    }


def build_proposed_experiment_plan(
    entry: dict[str, Any],
    signals: set[str],
    material_audit: dict[str, Any],
    result_analysis: dict[str, Any],
    linked_evidence_ids: list[str],
    literature_context: dict[str, Any] | None = None,
    historical_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    process_type = str(entry.get("process_type", ""))
    if "emulsion" in process_type.lower() and "polymer" in process_type.lower():
        return build_emulsion_polymerization_plan(
            entry,
            signals,
            material_audit,
            result_analysis,
            linked_evidence_ids,
            literature_context,
            historical_context,
        )
    experiment_id = str(entry.get("experiment_id", "unassigned"))
    suggested_experiment_id = str(entry.get("suggested_experiment_id", "")).strip() or f"{experiment_id}-FUP-001"
    return {
        "parent_experiment_id": experiment_id,
        "suggested_experiment_id": suggested_experiment_id,
        "process_type": process_type,
        "objective": f"Follow up {entry.get('objective', 'the current objective')} with one isolated variable.",
        "hypothesis": "Changing one variable at a time will make the result interpretable.",
        "variables": [
            {
                "factor": "single_selected_variable",
                "levels": ["baseline", "one intentional change"],
                "rationale": "The current process type does not yet have a specialized DOE template.",
            }
        ],
        "controls": ["Repeat the current best-known condition."],
        "measurements": ["record primary result metric", "record observations", "record deviations"],
        "acceptance_criteria": ["Result can be attributed to the selected variable."],
        "prerequisites": material_audit.get("recommendations", []),
        "result_support": result_plan_support(result_analysis),
        "linked_evidence_ids": linked_evidence_ids,
        "literature_support": literature_plan_support(literature_context),
        "history_support": history_plan_support(historical_context),
    }


def build_emulsion_polymerization_plan(
    entry: dict[str, Any],
    signals: set[str],
    material_audit: dict[str, Any],
    result_analysis: dict[str, Any],
    linked_evidence_ids: list[str],
    literature_context: dict[str, Any] | None = None,
    historical_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    experiment_id = str(entry.get("experiment_id", "EP"))
    suggested_experiment_id = str(entry.get("suggested_experiment_id", "")).strip() or f"{experiment_id}-FUP-001"
    focus = emulsion_followup_focus(signals)
    variables = [
        {
            "factor": "baseline_repeat",
            "levels": ["repeat current formulation exactly"],
            "rationale": "Provides a control for run-to-run variation before interpreting formulation changes.",
        }
    ]
    if "particle_size_high" in signals:
        variables.append(
            {
                "factor": "surfactant_active_basis_or_feed_duration",
                "levels": ["current surfactant/feed", "modestly higher surfactant active basis or slower monomer feed"],
                "rationale": "Particle size above target suggests nucleation/stabilization or feed-rate limitation.",
            }
        )
    if "coagulum" in signals or "instability" in signals:
        variables.append(
            {
                "factor": "surfactant_package",
                "levels": ["current package", "same active mass with mixed ionic/nonionic package"],
                "rationale": "Coagulum or visible instability points to colloidal stabilization as a first variable to isolate.",
            }
        )
    if "low_conversion" in signals:
        variables.append(
            {
                "factor": "initiator_process_health",
                "levels": ["current initiator feed", "verified fresh initiator and optional chase after baseline"],
                "rationale": "Low conversion can confound particle-size and stability interpretation.",
            }
        )
    if len(variables) == 1:
        variables.append(
            {
                "factor": "surfactant_level_x_feed_duration",
                "levels": ["current", "surfactant +10-20% or feed duration +25%"],
                "rationale": "Default emulsion-polymerization screen when no stronger failure signal is present.",
            }
        )

    prerequisites = []
    if not material_audit.get("ready_for_quantitative_suggestion", False):
        prerequisites.extend(material_audit.get("recommendations", []))

    planned_formulation_adjustments = formulation_adjustments_for_followup(
        entry,
        signals,
        literature_context,
    )

    return {
        "parent_experiment_id": experiment_id,
        "suggested_experiment_id": suggested_experiment_id,
        "process_type": "emulsion polymerization",
        "objective": focus["plan_objective"],
        "hypothesis": focus["plan_hypothesis"],
        "variables": variables,
        "controls": [
            "Repeat the current formulation as a baseline if material quantities are complete.",
            "Keep monomer identity, target solids, temperature, agitation, and total initiator basis fixed across arms.",
        ],
        "formulation_strategy": [
            "Use existing reagent_id values from Master Reagents and Formulations.",
            "Change only one primary factor per arm unless deliberately running a small DOE.",
            "Record mass_g, volume_mL, moles_mmol, concentration, feed_start_min, and feed_duration_min for every formulation row.",
        ],
        "measurements": [
            "particle_size_nm",
            "solids_percent",
            "conversion_percent",
            "coagulum_mass_g",
            "pH",
            "temperature_C",
            "viscosity_cP",
            "observation",
        ],
        "acceptance_criteria": focus["acceptance_criteria"],
        "prerequisites": prerequisites,
        "result_support": result_plan_support(result_analysis),
        "linked_evidence_ids": linked_evidence_ids,
        "literature_support": literature_plan_support(literature_context),
        "history_support": history_plan_support(historical_context),
        "planned_formulation_adjustments": planned_formulation_adjustments,
        "sheet_rows": {
            "experiments": [
                {
                    "experiment_id": suggested_experiment_id,
                    "process_type": "emulsion polymerization",
                    "objective": focus["sheet_objective"],
                    "hypothesis": focus["sheet_hypothesis"],
                    "linked_literature_ids": ",".join(linked_evidence_ids),
                    "status": "planned",
                }
            ],
            "formulations": formulation_rows_for_followup(
                entry,
                suggested_experiment_id,
                variables,
                planned_formulation_adjustments,
            ),
            "results_to_capture": [
                {"measurement_type": measurement, "units": suggested_units(measurement)}
                for measurement in (
                    "particle_size_nm",
                    "solids_percent",
                    "conversion_percent",
                    "coagulum_mass_g",
                    "pH",
                    "viscosity_cP",
                )
            ],
        },
    }


def emulsion_followup_focus(signals: set[str]) -> dict[str, Any]:
    has_particle = "particle_size_high" in signals
    has_stability = "coagulum" in signals or "instability" in signals
    has_conversion = "low_conversion" in signals
    if has_conversion and not has_particle and not has_stability:
        return {
            "proposal_base": (
                "Run a controlled emulsion polymerization follow-up that keeps "
                "monomer identity, target solids, surfactant package, feed "
                "profile, temperature, and agitation fixed while verifying "
                "process-health variables that control conversion."
            ),
            "plan_objective": (
                "Verify whether low conversion is driven by initiator freshness, "
                "oxygen removal, thermal hold, or chase strategy while keeping "
                "the latex formulation fixed."
            ),
            "plan_hypothesis": (
                "Holding monomer, surfactant, and feed profile fixed while "
                "verifying initiator and purge/temperature controls will raise "
                "conversion if process health is limiting."
            ),
            "sheet_objective": "Follow up low conversion by isolating initiator/process-health controls.",
            "sheet_hypothesis": (
                "Conversion improves when initiator freshness, purge quality, "
                "and thermal hold are verified while formulation is held fixed."
            ),
            "acceptance_criteria": [
                "Conversion moves above the 85% first-pass target without changing monomer identity.",
                "Particle size and coagulum do not regress relative to the baseline repeat.",
                "Initiator lot/freshness, purge time, temperature profile, and hold/chase details are recorded.",
                "No new safety or handling issue appears during feed, hold, or workup.",
            ],
        }
    if has_conversion:
        return {
            "proposal_base": (
                "Run a controlled emulsion polymerization follow-up that keeps "
                "monomer identity, target solids, temperature, and agitation "
                "fixed while separating latex-stability variables from "
                "initiator/process-health variables."
            ),
            "plan_objective": (
                "Isolate whether latex particle size, coagulum, and low "
                "conversion are controlled by surfactant package, feed profile, "
                "or process health."
            ),
            "plan_hypothesis": (
                "Holding monomer identity, target solids, temperature, and "
                "agitation fixed while separating surfactant/feed variables from "
                "initiator controls will show whether stability or conversion is "
                "the primary limitation."
            ),
            "sheet_objective": "Follow up latex stability and conversion by isolating surfactant/feed and process-health controls.",
            "sheet_hypothesis": "Stability and conversion improve when surfactant/feed variables and initiator process health are isolated.",
            "acceptance_criteria": [
                "Particle size moves toward the 200-350 nm target window when particle size is limiting.",
                "Coagulum mass decreases relative to the baseline repeat when stability is limiting.",
                "Conversion moves above the 85% first-pass target so stability changes are interpretable.",
                "No new safety or handling issue appears during feed, hold, or workup.",
            ],
        }
    if has_particle or has_stability:
        return {
            "proposal_base": (
                "Run a controlled emulsion polymerization follow-up that keeps "
                "monomer identity, target solids, temperature, agitation, and "
                "total initiator basis fixed while changing only the "
                "latex-stability variables."
            ),
            "plan_objective": "Isolate whether latex particle size and coagulum are controlled by surfactant package, feed profile, or process health.",
            "plan_hypothesis": "Holding monomer identity, target solids, temperature, agitation, and initiator basis fixed while changing latex-stability variables will lower particle size and reduce coagulum if colloidal stabilization/feed profile is limiting.",
            "sheet_objective": "Follow up latex particle size/coagulum by isolating surfactant package and feed profile.",
            "sheet_hypothesis": "Latex stability and particle size improve when surfactant/feed variables are isolated while core chemistry is held fixed.",
            "acceptance_criteria": [
                "Particle size moves toward the 200-350 nm target window.",
                "Coagulum mass decreases relative to the baseline repeat.",
                "Conversion remains high enough that stability changes are not confounded by incomplete polymerization.",
                "No new safety or handling issue appears during feed, hold, or workup.",
            ],
        }
    return {
        "proposal_base": (
            "Run a controlled emulsion polymerization follow-up that repeats the "
            "current formulation as a baseline and changes only one surfactant, "
            "feed, or process factor."
        ),
        "plan_objective": "Use the current emulsion polymerization run as a baseline and isolate one formulation or process variable.",
        "plan_hypothesis": "A single controlled change around the baseline will make the next particle-size, stability, and conversion results interpretable.",
        "sheet_objective": "Follow up the baseline by isolating one surfactant, feed, or process variable.",
        "sheet_hypothesis": "One controlled change around the baseline will identify the next useful process direction.",
        "acceptance_criteria": [
            "Primary measurements are captured for particle size, conversion, solids, and coagulum.",
            "The changed factor is the only intentional difference from the baseline repeat.",
            "Result direction is clear enough to choose the next formulation or process variable.",
            "No new safety or handling issue appears during feed, hold, or workup.",
        ],
    }


def literature_plan_support(literature_context: dict[str, Any] | None) -> dict[str, Any]:
    context = literature_context or {}
    return {
        "evidence_count": context.get("evidence_count", 0),
        "evidence_ids": context.get("evidence_ids", []),
        "relevance_tags": context.get("relevance_tags", []),
        "guidance": context.get("guidance", []),
        "supporting_findings": context.get("supporting_findings", []),
    }


def result_plan_support(result_analysis: dict[str, Any] | None) -> dict[str, Any]:
    analysis = result_analysis or {}
    return {
        "summary": analysis.get("summary", ""),
        "signals": analysis.get("signals", []),
        "limiting_metrics": analysis.get("limiting_metrics", []),
        "guidance": analysis.get("guidance", []),
    }


def history_plan_support(historical_context: dict[str, Any] | None) -> dict[str, Any]:
    context = historical_context or {}
    return {
        "prior_experiment_count": context.get("prior_experiment_count", 0),
        "prior_experiments": context.get("prior_experiments", []),
        "measurement_benchmarks": context.get("measurement_benchmarks", []),
        "guidance": context.get("guidance", []),
    }


def formulation_adjustments_for_followup(
    entry: dict[str, Any],
    signals: set[str],
    literature_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    formulation = [row for row in entry.get("formulation", []) or [] if isinstance(row, dict)]
    adjustments: list[dict[str, Any]] = []
    literature_tags = {str(tag) for tag in (literature_context or {}).get("relevance_tags", [])}

    surfactant = first_formulation_row(formulation, {"surfactant"})
    monomer = first_formulation_row(formulation, {"core_monomer", "shell_monomer", "comonomer", "monomer"})
    initiator = first_formulation_row(formulation, {"initiator"})

    if "particle_size_high" in signals:
        surfactant_basis = first_numeric_field(surfactant[1] if surfactant else {}, ("mass_g", "wt_percent"))
        if surfactant and surfactant_basis:
            adjustment = scaled_formulation_adjustment(
                surfactant[0],
                surfactant[1],
                surfactant_basis,
                1.15,
                (
                    "Particle size is above target; modestly increase surfactant "
                    "active basis for the follow-up."
                ),
            )
            if adjustment:
                adjustments.append(adjustment)
        else:
            feed_reason = (
                "Particle size is above target and no numeric surfactant basis "
                "is available; slow the monomer feed for the follow-up."
            )
            if "feed" in literature_tags:
                feed_reason += " Linked evidence also flags feed/nucleation sensitivity."
            adjustment = scaled_formulation_adjustment(
                monomer[0] if monomer else 0,
                monomer[1] if monomer else {},
                "feed_duration_min",
                1.25,
                feed_reason,
            )
            if adjustment:
                adjustments.append(adjustment)
            elif surfactant:
                adjustments.append(
                    note_formulation_adjustment(
                        surfactant[0],
                        surfactant[1],
                        (
                            "No numeric surfactant basis or monomer feed duration "
                            "was available; review a +10-20% surfactant active-basis "
                            "arm before execution."
                        ),
                    )
                )

    if ("coagulum" in signals or "instability" in signals) and surfactant:
        adjustments.append(
            note_formulation_adjustment(
                surfactant[0],
                surfactant[1],
                (
                    "Coagulum or instability was observed; review whether a mixed "
                    "ionic/nonionic surfactant package should be tested at the same "
                    "active basis."
                ),
            )
        )

    if "low_conversion" in signals and initiator:
        adjustments.append(
            note_formulation_adjustment(
                initiator[0],
                initiator[1],
                (
                    "Low conversion was detected; verify initiator freshness, purge "
                    "quality, and whether a chase feed is needed after reproducing "
                    "the baseline."
                ),
            )
        )

    return adjustments


def first_formulation_row(
    formulation: list[dict[str, Any]],
    target_roles: set[str],
) -> tuple[int, dict[str, Any]] | None:
    for index, row in enumerate(formulation, start=1):
        target_role = str(row.get("target_role", "")).strip().lower()
        reagent_category = str(row.get("reagent_category", "")).strip().lower()
        nested_reagent = row.get("reagent") if isinstance(row.get("reagent"), dict) else {}
        nested_category = str(nested_reagent.get("category", "")).strip().lower()
        if target_role in target_roles or reagent_category in target_roles or nested_category in target_roles:
            return index, row
    return None


def first_numeric_field(row: dict[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        if coerce_float(row.get(field)) is not None:
            return field
    return ""


def scaled_formulation_adjustment(
    source_index: int,
    row: dict[str, Any],
    field: str,
    scale_factor: float,
    rationale: str,
) -> dict[str, Any] | None:
    value = coerce_float(row.get(field))
    if source_index <= 0 or value is None:
        return None
    proposed = format_numeric_for_sheet(value * scale_factor)
    return {
        "source_index": source_index,
        "reagent_id": row.get("reagent_id", ""),
        "target_role": row.get("target_role", ""),
        "field": field,
        "parent_value": row.get(field, ""),
        "proposed_value": proposed,
        "scale_factor": scale_factor,
        "rationale": rationale,
    }


def note_formulation_adjustment(
    source_index: int,
    row: dict[str, Any],
    note: str,
) -> dict[str, Any]:
    return {
        "source_index": source_index,
        "reagent_id": row.get("reagent_id", ""),
        "target_role": row.get("target_role", ""),
        "field": "notes",
        "parent_value": row.get("notes", ""),
        "proposed_value": note,
        "rationale": note,
    }


def format_numeric_for_sheet(value: float) -> str:
    return f"{value:.6g}"


def formulation_rows_for_followup(
    entry: dict[str, Any],
    suggested_experiment_id: str,
    variables: list[dict[str, Any]],
    planned_adjustments: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    factor_text = ", ".join(str(variable.get("factor", "")) for variable in variables if variable.get("factor"))
    adjustments_by_index: dict[int, list[dict[str, Any]]] = {}
    for adjustment in planned_adjustments or []:
        source_index = int(adjustment.get("source_index", 0) or 0)
        if source_index:
            adjustments_by_index.setdefault(source_index, []).append(adjustment)
    rows = []
    for index, source_row in enumerate(entry.get("formulation", []) or [], start=1):
        if not isinstance(source_row, dict):
            continue
        row_adjustments = adjustments_by_index.get(index, [])
        row = {
            "experiment_id": suggested_experiment_id,
            "reagent_id": source_row.get("reagent_id", ""),
            "phase": source_row.get("phase", ""),
            "target_role": source_row.get("target_role", ""),
            "mass_g": source_row.get("mass_g", ""),
            "volume_mL": source_row.get("volume_mL", ""),
            "moles_mmol": source_row.get("moles_mmol", ""),
            "concentration": source_row.get("concentration", ""),
            "concentration_units": source_row.get("concentration_units", ""),
            "wt_percent": source_row.get("wt_percent", ""),
            "feed_order": source_row.get("feed_order", index),
            "feed_start_min": source_row.get("feed_start_min", ""),
            "feed_duration_min": source_row.get("feed_duration_min", ""),
            "notes": followup_formulation_note(source_row, factor_text, row_adjustments),
        }
        for adjustment in row_adjustments:
            field = str(adjustment.get("field", ""))
            if field in row and field != "notes":
                row[field] = adjustment.get("proposed_value", row[field])
        if row["reagent_id"] and row["target_role"]:
            rows.append(row)
    return rows


def followup_formulation_note(
    source_row: dict[str, Any],
    factor_text: str,
    adjustments: list[dict[str, Any]] | None = None,
) -> str:
    source_note = str(source_row.get("notes", "")).strip()
    parts = [
        "Draft follow-up row copied from parent formulation; verify quantities before running.",
    ]
    if factor_text:
        parts.append(f"Planned variables: {factor_text}.")
    field_adjustments = [
        adjustment
        for adjustment in adjustments or []
        if str(adjustment.get("field", "")) != "notes"
    ]
    note_adjustments = [
        adjustment
        for adjustment in adjustments or []
        if str(adjustment.get("field", "")) == "notes"
    ]
    if field_adjustments:
        parts.append(
            "Applied planned adjustments: "
            + "; ".join(
                (
                    f"{adjustment.get('field', '')} "
                    f"{adjustment.get('parent_value', '')} -> "
                    f"{adjustment.get('proposed_value', '')}"
                )
                for adjustment in field_adjustments
            )
            + "."
        )
    for adjustment in note_adjustments:
        proposed_note = str(adjustment.get("proposed_value", "")).strip()
        if proposed_note:
            parts.append(f"Review note: {proposed_note}")
    if source_note:
        parts.append(f"Parent notes: {source_note}")
    return " ".join(parts)


def suggested_units(measurement: str) -> str:
    return {
        "particle_size_nm": "nm",
        "solids_percent": "%",
        "conversion_percent": "%",
        "coagulum_mass_g": "g",
        "pH": "",
        "viscosity_cP": "cP",
    }.get(measurement, "")
