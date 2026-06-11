from __future__ import annotations

from typing import Any


def build_historical_result_context(
    tables: dict[str, list[dict[str, Any]]],
    experiment_id: str,
    limit: int = 5,
) -> dict[str, Any]:
    experiments = [
        row
        for row in tables.get("Experiments", [])
        if isinstance(row, dict) and str(row.get("experiment_id", "")).strip()
    ]
    current = next((row for row in experiments if str(row.get("experiment_id", "")).strip() == experiment_id), {})
    process_type = str(current.get("process_type", "")).strip().lower()
    results_by_experiment = group_rows_by_experiment(tables.get("Results", []))
    current_results = results_by_experiment.get(experiment_id, [])
    prior_experiments = []
    for row in experiments:
        prior_id = str(row.get("experiment_id", "")).strip()
        if not prior_id or prior_id == experiment_id:
            continue
        status = str(row.get("status", "")).strip().lower()
        if status == "abandoned":
            continue
        if process_type and str(row.get("process_type", "")).strip().lower() != process_type:
            continue
        prior_experiments.append(row)

    prior_experiments = sorted(
        prior_experiments,
        key=lambda row: str(row.get("date", "")),
        reverse=True,
    )[: max(limit, 0)]
    prior_summaries = [
        experiment_result_summary(row, results_by_experiment.get(str(row.get("experiment_id", "")).strip(), []))
        for row in prior_experiments
    ]
    benchmarks = measurement_benchmarks(prior_summaries)
    guidance = historical_guidance(current_results, prior_summaries, benchmarks)
    return {
        "experiment_id": experiment_id,
        "process_type": current.get("process_type", ""),
        "prior_experiment_count": len(prior_summaries),
        "prior_experiments": prior_summaries,
        "measurement_benchmarks": benchmarks,
        "guidance": guidance,
    }


def group_rows_by_experiment(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        experiment_id = str(row.get("experiment_id", "")).strip()
        if not experiment_id:
            continue
        grouped.setdefault(experiment_id, []).append(row)
    return grouped


def experiment_result_summary(experiment: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "experiment_id": experiment.get("experiment_id", ""),
        "date": experiment.get("date", ""),
        "status": experiment.get("status", ""),
        "objective": experiment.get("objective", ""),
        "summary": experiment.get("summary", ""),
        "measurements": [measurement_summary(row) for row in results if isinstance(row, dict)],
    }


def measurement_summary(row: dict[str, Any]) -> dict[str, Any]:
    numeric_value = coerce_float(row.get("value"))
    summary = {
        "measurement_type": row.get("measurement_type", ""),
        "value": row.get("value", ""),
        "units": row.get("units", ""),
        "quality_flag": row.get("quality_flag", ""),
        "interpretation": row.get("interpretation", ""),
    }
    if numeric_value is not None:
        summary["numeric_value"] = numeric_value
        summary["metric_key"] = metric_key(row.get("measurement_type", ""), row.get("units", ""))
    return summary


def measurement_benchmarks(prior_summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[tuple[float, str, str]]] = {}
    for experiment in prior_summaries:
        experiment_id = str(experiment.get("experiment_id", ""))
        for measurement in experiment.get("measurements", []) or []:
            key = str(measurement.get("metric_key", ""))
            value = measurement.get("numeric_value")
            if key and isinstance(value, (int, float)):
                grouped.setdefault(key, []).append((float(value), experiment_id, str(measurement.get("units", ""))))

    benchmarks = []
    for key, values in sorted(grouped.items()):
        numbers = [value for value, _, _ in values]
        min_value, min_experiment, units = min(values, key=lambda item: item[0])
        max_value, max_experiment, _ = max(values, key=lambda item: item[0])
        benchmarks.append(
            {
                "metric_key": key,
                "count": len(values),
                "units": units,
                "min": format_number(min_value),
                "min_experiment_id": min_experiment,
                "max": format_number(max_value),
                "max_experiment_id": max_experiment,
                "average": format_number(sum(numbers) / len(numbers)),
            }
        )
    return benchmarks


def historical_guidance(
    current_results: list[dict[str, Any]],
    prior_summaries: list[dict[str, Any]],
    benchmarks: list[dict[str, Any]],
) -> list[str]:
    if not prior_summaries:
        return []
    current_metrics = current_numeric_metrics(current_results)
    benchmark_by_key = {row["metric_key"]: row for row in benchmarks}
    guidance = []
    particle_size = current_metrics.get("particle_size")
    particle_benchmark = benchmark_by_key.get("particle_size")
    if particle_size is not None and particle_benchmark and float(particle_benchmark["min"]) < particle_size:
        guidance.append(
            "Prior experiment "
            f"{particle_benchmark['min_experiment_id']} reached lower particle size "
            f"({particle_benchmark['min']} {particle_benchmark['units']}); compare surfactant/feed conditions before changing monomers."
        )
    conversion = current_metrics.get("conversion")
    conversion_benchmark = benchmark_by_key.get("conversion")
    if conversion is not None and conversion_benchmark and float(conversion_benchmark["max"]) > conversion:
        guidance.append(
            "Prior experiment "
            f"{conversion_benchmark['max_experiment_id']} reached higher conversion "
            f"({conversion_benchmark['max']} {conversion_benchmark['units']}); check initiator, purge, and hold conditions."
        )
    coagulum = current_metrics.get("coagulum_mass")
    coagulum_benchmark = benchmark_by_key.get("coagulum_mass")
    if coagulum is not None and coagulum_benchmark and float(coagulum_benchmark["min"]) < coagulum:
        guidance.append(
            "Prior experiment "
            f"{coagulum_benchmark['min_experiment_id']} had lower coagulum "
            f"({coagulum_benchmark['min']} {coagulum_benchmark['units']}); preserve known-good stability variables as controls."
        )
    if not guidance:
        guidance.append("Use same-process prior experiments as controls when choosing the next variable to isolate.")
    return guidance


def current_numeric_metrics(results: list[dict[str, Any]]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for row in results:
        if not isinstance(row, dict):
            continue
        value = coerce_float(row.get("value"))
        if value is None:
            continue
        key = metric_key(row.get("measurement_type", ""), row.get("units", ""))
        if key and key not in metrics:
            metrics[key] = value
    return metrics


def metric_key(measurement_type: Any, units: Any = "") -> str:
    text = f"{measurement_type} {units}".lower()
    if "particle" in text or "dls" in text:
        return "particle_size"
    if "conversion" in text:
        return "conversion"
    if "coagulum" in text or "grit" in text:
        return "coagulum_mass"
    if "solids" in text:
        return "solids"
    if "viscosity" in text:
        return "viscosity"
    if "ph" in text:
        return "pH"
    return ""


def coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_number(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")
