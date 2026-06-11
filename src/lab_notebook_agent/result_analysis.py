from __future__ import annotations

from typing import Any

from .history import metric_key


EMULSION_TARGETS: dict[str, dict[str, Any]] = {
    "particle_size": {
        "label": "particle size target window",
        "min": 200.0,
        "max": 350.0,
        "units": "nm",
        "guidance_high": "Prioritize surfactant active basis, surfactant package, seed/nucleation, or feed duration before changing monomer identity.",
        "guidance_low": "Confirm the DLS method and sample dilution before optimizing around a very small particle-size value.",
    },
    "conversion": {
        "label": "conversion minimum",
        "min": 85.0,
        "units": "%",
        "guidance_low": "Check initiator freshness, purge quality, thermal hold, and chase strategy before interpreting particle-size changes.",
    },
    "residual_monomer": {
        "label": "residual monomer maximum",
        "max": 1.0,
        "units": "%",
        "guidance_high": "Treat high residual monomer as a process-health limitation; verify initiator, purge, temperature profile, hold time, and chase strategy.",
    },
    "polydispersity_index": {
        "label": "DLS PDI maximum",
        "max": 0.2,
        "units": "",
        "guidance_high": "Treat broad particle-size distribution as a nucleation/stabilization signal; review surfactant package, seed/nucleation, feed duration, and sample prep.",
    },
    "coagulum_mass": {
        "label": "coagulum mass maximum",
        "max": 0.1,
        "units": "g",
        "guidance_high": "Treat colloidal stability as the first variable to isolate; compare surfactant package, ionic strength, pH, and feed conditions.",
    },
}

DAILY_LOG_METRIC_FIELDS: dict[str, tuple[str, str]] = {
    "particle_size_nm": ("DLS particle size", "nm"),
    "conversion_percent": ("conversion", "%"),
    "solids_percent": ("solids percent", "%"),
    "viscosity_cP": ("viscosity", "cP"),
    "pH": ("pH", ""),
}


def build_result_analysis(entry: dict[str, Any]) -> dict[str, Any]:
    process_type = str(entry.get("process_type", ""))
    targets = targets_for_process(process_type)
    observations = [row for row in entry.get("observations", []) or [] if isinstance(row, dict)]
    measurements = result_measurements(entry, observations)
    evaluated = [evaluate_measurement(row, targets) for row in measurements]
    qualitative_signals = qualitative_observation_signals(observations)
    signals = sorted({signal for row in evaluated for signal in row.get("signals", [])} | set(qualitative_signals))
    limiting_metrics = [
        row
        for row in evaluated
        if row.get("status") in {"above_target", "below_target"}
    ]
    limiting_metrics = sorted(limiting_metrics, key=lambda row: (row.get("priority", 99), row.get("metric_key", "")))
    guidance = result_guidance(limiting_metrics, qualitative_signals, bool(measurements), bool(targets))
    return {
        "schema": "lab-notebook-agent-result-analysis.v1",
        "experiment_id": entry.get("experiment_id", ""),
        "process_type": process_type,
        "target_profile": "emulsion polymerization" if targets else "",
        "measurements": evaluated,
        "limiting_metrics": [
            {
                "metric_key": row.get("metric_key", ""),
                "value": row.get("value", ""),
                "units": row.get("units", ""),
                "status": row.get("status", ""),
                "target": row.get("target", {}),
                "guidance": row.get("guidance", ""),
            }
            for row in limiting_metrics
        ],
        "signals": signals,
        "guidance": guidance,
        "summary": result_analysis_summary(evaluated, limiting_metrics, qualitative_signals),
    }


def targets_for_process(process_type: str) -> dict[str, dict[str, Any]]:
    normalized = process_type.lower()
    if "emulsion" in normalized and "polymer" in normalized:
        return EMULSION_TARGETS
    return {}


def result_measurements(
    entry: dict[str, Any],
    observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in entry.get("results", []) or []:
        if not isinstance(row, dict):
            continue
        value = coerce_float(row.get("value"))
        key = metric_key(row.get("measurement_type", ""), row.get("units", ""))
        if value is None or not key:
            continue
        rows.append(
            {
                "source": "Results",
                "metric_key": key,
                "measurement_type": row.get("measurement_type", ""),
                "sample_id": row.get("sample_id", ""),
                "value": value,
                "units": row.get("units", ""),
                "condition": row.get("condition", ""),
                "quality_flag": row.get("quality_flag", ""),
            }
        )
    for row in observations:
        timestamp = row.get("timestamp", "")
        for field, (measurement_type, units) in DAILY_LOG_METRIC_FIELDS.items():
            value = coerce_float(row.get(field))
            if value is None:
                continue
            rows.append(
                {
                    "source": "Daily Log",
                    "metric_key": metric_key(measurement_type, units),
                    "measurement_type": measurement_type,
                    "sample_id": "",
                    "value": value,
                    "units": units,
                    "condition": timestamp,
                    "quality_flag": "observed",
                }
            )
    return dedupe_measurements(rows)


def dedupe_measurements(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, float, str]] = set()
    deduped = []
    for row in rows:
        key = (
            str(row.get("metric_key", "")),
            float(row.get("value", 0)),
            str(row.get("units", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def evaluate_measurement(row: dict[str, Any], targets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    evaluated = dict(row)
    metric = str(row.get("metric_key", ""))
    target = targets.get(metric)
    evaluated["target"] = target_summary(target)
    evaluated["status"] = "no_target"
    evaluated["signals"] = []
    evaluated["priority"] = 99
    evaluated["guidance"] = ""
    value = coerce_float(row.get("value"))
    if target is None or value is None:
        return evaluated
    low = target.get("min")
    high = target.get("max")
    if low is not None and value < float(low):
        evaluated["status"] = "below_target"
        evaluated["signals"] = signals_for_metric(metric, "below_target")
        evaluated["priority"] = priority_for_metric(metric)
        evaluated["guidance"] = str(target.get("guidance_low", ""))
    elif high is not None and value > float(high):
        evaluated["status"] = "above_target"
        evaluated["signals"] = signals_for_metric(metric, "above_target")
        evaluated["priority"] = priority_for_metric(metric)
        evaluated["guidance"] = str(target.get("guidance_high", ""))
    else:
        evaluated["status"] = "in_target"
    return evaluated


def target_summary(target: dict[str, Any] | None) -> dict[str, Any]:
    if not target:
        return {}
    return {
        key: target[key]
        for key in ("label", "min", "max", "units")
        if key in target
    }


def signals_for_metric(metric: str, status: str) -> list[str]:
    if metric == "particle_size" and status == "above_target":
        return ["particle_size_high"]
    if metric == "particle_size" and status == "below_target":
        return ["particle_size_low"]
    if metric == "conversion" and status == "below_target":
        return ["low_conversion"]
    if metric == "residual_monomer" and status == "above_target":
        return ["residual_monomer_high", "low_conversion"]
    if metric == "polydispersity_index" and status == "above_target":
        return ["broad_psd"]
    if metric == "coagulum_mass" and status == "above_target":
        return ["coagulum"]
    return []


def priority_for_metric(metric: str) -> int:
    return {
        "coagulum_mass": 1,
        "conversion": 2,
        "residual_monomer": 2,
        "particle_size": 3,
        "polydispersity_index": 4,
    }.get(metric, 50)


def qualitative_observation_signals(observations: list[dict[str, Any]]) -> list[str]:
    signals = set()
    for row in observations:
        text = " ".join(
            [
                str(row.get("observation", "")),
                str(row.get("issue_tags", "")),
            ]
        ).lower()
        if any(term in text for term in ("coagulum", "coagulated", "grit", "phase separation")):
            signals.add("coagulum")
        if "low_conversion" in text or "low conversion" in text:
            signals.add("low_conversion")
        if "residual_monomer" in text or "residual monomer" in text:
            signals.add("residual_monomer_high")
        if "particle_size_high" in text or "particle size high" in text:
            signals.add("particle_size_high")
        if "broad_psd" in text or "broad psd" in text or "high pdi" in text:
            signals.add("broad_psd")
    return sorted(signals)


def result_guidance(
    limiting_metrics: list[dict[str, Any]],
    qualitative_signals: list[str],
    has_measurements: bool,
    has_targets: bool,
) -> list[str]:
    if not has_measurements:
        return ["Add normalized Results rows before asking the agent to interpret the experiment outcome."]
    if not has_targets:
        return ["No process-specific target profile is available; interpret measurements manually and isolate one variable in the next run."]
    guidance = []
    for row in limiting_metrics:
        text = str(row.get("guidance", "")).strip()
        if text and text not in guidance:
            guidance.append(text)
    if "coagulum" in qualitative_signals and not any("colloidal stability" in item for item in guidance):
        guidance.append("Qualitative coagulum or instability was recorded; treat stability as a gating criterion even if no coagulum mass was measured.")
    if not guidance:
        guidance.append("Measured outcomes are within the first-pass target profile; use this run as a candidate control before expanding variables.")
    return guidance


def result_analysis_summary(
    measurements: list[dict[str, Any]],
    limiting_metrics: list[dict[str, Any]],
    qualitative_signals: list[str],
) -> str:
    if not measurements:
        return "No numeric Results or structured Daily Log measurements were available for target comparison."
    if limiting_metrics:
        parts = [
            f"{row.get('metric_key')} {format_value(row.get('value'))} {row.get('units', '')}".strip()
            + f" is {row.get('status', '')}"
            for row in limiting_metrics[:3]
        ]
        return "Outcome limits: " + "; ".join(parts) + "."
    if qualitative_signals:
        return "Numeric measurements were in target where targets exist, but qualitative signals remain: " + ", ".join(qualitative_signals) + "."
    return "Numeric measurements are within the first-pass target profile where targets exist."


def coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).strip().split()[0])
    except (TypeError, ValueError):
        return None


def format_value(value: Any) -> str:
    number = coerce_float(value)
    if number is None:
        return str(value)
    return f"{number:.6f}".rstrip("0").rstrip(".")
