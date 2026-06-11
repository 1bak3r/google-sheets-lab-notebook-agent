from __future__ import annotations

from typing import Any


PROCESS_ROLE_GROUPS: dict[str, list[dict[str, Any]]] = {
    "emulsion polymerization": [
        {
            "role_group": "monomer",
            "acceptable_roles": ["core_monomer", "shell_monomer", "comonomer", "monomer"],
            "examples": ["acrylate monomer", "methacrylate monomer", "functional comonomer"],
            "required": True,
            "important_reagent_fields": ["molecular_weight_g_mol", "density_g_mL"],
        },
        {
            "role_group": "initiator",
            "acceptable_roles": ["initiator"],
            "examples": ["ammonium persulfate", "potassium persulfate", "redox initiator"],
            "required": True,
            "important_reagent_fields": ["molecular_weight_g_mol"],
        },
        {
            "role_group": "surfactant",
            "acceptable_roles": ["surfactant"],
            "examples": ["anionic surfactant", "nonionic surfactant", "mixed surfactant package"],
            "required": True,
            "important_reagent_fields": ["molecular_weight_g_mol", "concentration"],
        },
        {
            "role_group": "aqueous_phase",
            "acceptable_roles": ["solvent", "buffer", "neutralizer"],
            "examples": ["deionized water", "buffer", "pH adjuster"],
            "required": False,
            "important_reagent_fields": [],
        },
        {
            "role_group": "crosslinker_or_chain_transfer",
            "acceptable_roles": ["crosslinker", "chain_transfer_agent"],
            "examples": ["divinyl ester", "diacrylate", "chain transfer agent"],
            "required": False,
            "important_reagent_fields": ["molecular_weight_g_mol"],
        },
    ],
}

QUANTITY_FIELDS = ("mass_g", "volume_mL", "moles_mmol", "wt_percent", "concentration")


def audit_experiment_materials(entry: dict[str, Any]) -> dict[str, Any]:
    process_type = str(entry.get("process_type", "")).lower()
    role_specs = role_specs_for_process(process_type)
    formulation = [row for row in entry.get("formulation", []) or [] if isinstance(row, dict)]
    role_groups = [audit_role_group(spec, formulation) for spec in role_specs]
    missing_required = [
        group["role_group"]
        for group in role_groups
        if group["required"] and group["status"] == "missing"
    ]
    quantity_gaps = formulation_quantity_gaps(formulation)
    property_gaps = formulation_property_gaps(formulation, role_specs)
    calculations = [calculate_formulation_row(row) for row in formulation]
    calculation_gaps = [row for row in calculations if row["missing_for_calculations"]]
    ready = not missing_required and not quantity_gaps and not property_gaps
    recommendations = material_audit_recommendations(missing_required, quantity_gaps, property_gaps)
    return {
        "process_type": entry.get("process_type", ""),
        "role_groups": role_groups,
        "missing_required_role_groups": missing_required,
        "quantity_gaps": quantity_gaps,
        "reagent_property_gaps": property_gaps,
        "formulation_calculations": calculations,
        "calculation_gaps": calculation_gaps,
        "ready_for_quantitative_suggestion": ready,
        "recommendations": recommendations,
        "summary": material_audit_summary(missing_required, quantity_gaps, property_gaps),
    }


def role_specs_for_process(process_type: str) -> list[dict[str, Any]]:
    if "emulsion" in process_type and "polymer" in process_type:
        return PROCESS_ROLE_GROUPS["emulsion polymerization"]
    return []


def audit_role_group(spec: dict[str, Any], formulation: list[dict[str, Any]]) -> dict[str, Any]:
    acceptable = {role.lower() for role in spec["acceptable_roles"]}
    present = [
        row
        for row in formulation
        if str(row.get("target_role", "")).lower() in acceptable
        or str(row.get("reagent_category", "")).lower() in acceptable
        or str((row.get("reagent") or {}).get("category", "")).lower() in acceptable
    ]
    return {
        "role_group": spec["role_group"],
        "required": spec["required"],
        "acceptable_roles": spec["acceptable_roles"],
        "examples": spec["examples"],
        "status": "present" if present else "missing",
        "present_reagent_ids": [str(row.get("reagent_id", "")) for row in present if row.get("reagent_id")],
        "present_roles": sorted({str(row.get("target_role", "")) for row in present if row.get("target_role")}),
    }


def formulation_quantity_gaps(formulation: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gaps = []
    for row in formulation:
        if any(nonblank(row.get(field)) for field in QUANTITY_FIELDS):
            continue
        gaps.append(
            {
                "reagent_id": row.get("reagent_id", ""),
                "target_role": row.get("target_role", ""),
                "phase": row.get("phase", ""),
                "missing_any_of": list(QUANTITY_FIELDS),
            }
        )
    return gaps


def formulation_property_gaps(
    formulation: list[dict[str, Any]],
    role_specs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    gaps = []
    for row in formulation:
        fields = important_fields_for_row(row, role_specs)
        missing = [field for field in fields if not row_has_reagent_property(row, field)]
        if missing:
            gaps.append(
                {
                    "reagent_id": row.get("reagent_id", ""),
                    "target_role": row.get("target_role", ""),
                    "missing_fields": missing,
                }
            )
    return gaps


def important_fields_for_row(row: dict[str, Any], role_specs: list[dict[str, Any]]) -> list[str]:
    target_role = str(row.get("target_role", "")).lower()
    fields: list[str] = []
    for spec in role_specs:
        if target_role in {role.lower() for role in spec["acceptable_roles"]}:
            fields.extend(spec.get("important_reagent_fields", []))
    return sorted(set(fields))


def row_has_reagent_property(row: dict[str, Any], field: str) -> bool:
    return nonblank(row.get(field)) or nonblank(row.get(f"reagent_{field}")) or nonblank((row.get("reagent") or {}).get(field))


def calculate_formulation_row(row: dict[str, Any]) -> dict[str, Any]:
    observed = {
        "mass_g": numeric_value(row.get("mass_g")),
        "volume_mL": numeric_value(row.get("volume_mL")),
        "moles_mmol": numeric_value(row.get("moles_mmol")),
        "molecular_weight_g_mol": numeric_reagent_property(row, "molecular_weight_g_mol"),
        "density_g_mL": numeric_reagent_property(row, "density_g_mL"),
        "purity_fraction": numeric_reagent_fraction(row, "purity_fraction"),
        "concentration": numeric_reagent_property(row, "concentration"),
        "concentration_units": reagent_property_text(row, "concentration_units"),
    }
    derived: dict[str, float] = {}

    mass_g = observed["mass_g"]
    volume_mL = observed["volume_mL"]
    moles_mmol = observed["moles_mmol"]
    molecular_weight = observed["molecular_weight_g_mol"]
    density = observed["density_g_mL"]
    purity = observed["purity_fraction"] or 1.0
    concentration = observed["concentration"]
    concentration_units = observed["concentration_units"]
    concentration_fraction = concentration_to_fraction(concentration, concentration_units)
    stock_active_mass_g: float | None = None
    moles_from_stock_concentration = False

    molarity = concentration_to_molarity_mmol_per_mL(concentration, concentration_units)
    if moles_mmol is None and volume_mL is not None and molarity is not None:
        moles_mmol = volume_mL * molarity
        moles_from_stock_concentration = True
        derived["moles_mmol"] = round(moles_mmol, 6)
        if molecular_weight is not None:
            stock_active_mass_g = (moles_mmol / 1000) * molecular_weight
            derived["active_mass_g"] = round(stock_active_mass_g, 6)

    mass_concentration = concentration_to_mass_g_per_mL(concentration, concentration_units)
    if volume_mL is not None and mass_concentration is not None:
        stock_active_mass_g = volume_mL * mass_concentration
        derived["active_mass_g"] = round(stock_active_mass_g, 6)
        if moles_mmol is None and molecular_weight is not None:
            moles_mmol = (stock_active_mass_g / molecular_weight) * 1000
            moles_from_stock_concentration = True
            derived["moles_mmol"] = round(moles_mmol, 6)

    if mass_g is None and volume_mL is not None and density is not None:
        mass_g = volume_mL * density
        derived["mass_g"] = round(mass_g, 6)
    if volume_mL is None and mass_g is not None and density is not None:
        volume_mL = mass_g / density
        derived["volume_mL"] = round(volume_mL, 6)
    if moles_mmol is None and mass_g is not None and molecular_weight is not None:
        if stock_active_mass_g is not None:
            active_mass_g = stock_active_mass_g
        elif concentration_fraction is not None:
            active_mass_g = mass_g * concentration_fraction
            derived["active_mass_g"] = round(active_mass_g, 6)
        elif concentration is not None and concentration_units:
            active_mass_g = None
        else:
            active_mass_g = mass_g * purity
            if purity != 1.0:
                derived["active_mass_g"] = round(active_mass_g, 6)
        if active_mass_g is not None:
            moles_mmol = (active_mass_g / molecular_weight) * 1000
            derived["moles_mmol"] = round(moles_mmol, 6)
    if (
        mass_g is None
        and moles_mmol is not None
        and molecular_weight is not None
        and not moles_from_stock_concentration
    ):
        active_mass_g = (moles_mmol / 1000) * molecular_weight
        if concentration_fraction is not None:
            mass_g = active_mass_g / concentration_fraction
            derived["active_mass_g"] = round(active_mass_g, 6)
        else:
            mass_g = active_mass_g / purity
        if purity != 1.0:
            derived["active_mass_g"] = round(active_mass_g, 6)
        derived["mass_g"] = round(mass_g, 6)
        if volume_mL is None and density is not None:
            volume_mL = mass_g / density
            derived["volume_mL"] = round(volume_mL, 6)

    missing = []
    target_role = str(row.get("target_role", ""))
    if any(role in target_role for role in ("monomer", "initiator", "surfactant", "crosslinker")):
        if moles_mmol is None:
            missing.append(
                "moles_mmol needs direct moles_mmol, mass_g plus molecular_weight_g_mol, "
                "or volume_mL plus stock concentration units"
            )
    if "monomer" in target_role and volume_mL is None:
        missing.append("volume_mL needs mass_g plus density_g_mL, volume_mL, or moles_mmol plus molecular_weight_g_mol and density_g_mL")

    return {
        "reagent_id": row.get("reagent_id", ""),
        "target_role": row.get("target_role", ""),
        "phase": row.get("phase", ""),
        "observed": {key: value for key, value in observed.items() if value is not None},
        "derived": derived,
        "missing_for_calculations": missing,
    }


def numeric_reagent_property(row: dict[str, Any], field: str) -> float | None:
    for value in reagent_property_values(row, field):
        number = numeric_value(value)
        if number is not None:
            return number
    return None


def numeric_reagent_fraction(row: dict[str, Any], field: str) -> float | None:
    for value in reagent_property_values(row, field):
        number = numeric_fraction_value(value)
        if number is not None:
            return number
    return None


def reagent_property_text(row: dict[str, Any], field: str) -> str | None:
    for value in reagent_property_values(row, field):
        if nonblank(value):
            return str(value).strip()
    return None


def reagent_property_values(row: dict[str, Any], field: str) -> list[Any]:
    reagent = row.get("reagent") if isinstance(row.get("reagent"), dict) else {}
    return [row.get(field), row.get(f"reagent_{field}"), reagent.get(field)]


def concentration_to_molarity_mmol_per_mL(concentration: float | None, units: str | None) -> float | None:
    if concentration is None or concentration <= 0:
        return None
    normalized = normalized_concentration_units(units)
    if normalized in {"m", "molar", "mol/l", "moll-1", "mol/liter", "mol/litre"}:
        return concentration
    if normalized in {"mm", "mmolar", "mmol/l", "mmoll-1", "mmol/liter", "mmol/litre"}:
        return concentration / 1000
    if normalized in {"um", "umolar", "umol/l", "umoll-1", "umol/liter", "umol/litre"}:
        return concentration / 1_000_000
    if normalized in {"mmol/ml", "mmolml-1"}:
        return concentration
    if normalized in {"mol/ml", "molml-1"}:
        return concentration * 1000
    return None


def concentration_to_mass_g_per_mL(concentration: float | None, units: str | None) -> float | None:
    if concentration is None or concentration <= 0:
        return None
    normalized = normalized_concentration_units(units)
    if normalized in {"g/ml", "gml-1"}:
        return concentration
    if normalized in {"mg/ml", "mgml-1"}:
        return concentration / 1000
    if normalized in {"ug/ml", "ugml-1"}:
        return concentration / 1_000_000
    if normalized in {"g/l", "gl-1"}:
        return concentration / 1000
    if normalized in {"mg/l", "mgl-1"}:
        return concentration / 1_000_000
    return None


def concentration_to_fraction(concentration: float | None, units: str | None) -> float | None:
    if concentration is None or concentration <= 0:
        return None
    normalized = normalized_concentration_units(units)
    if normalized in {"%", "percent", "wt%", "weight%", "weightpercent", "w/w%", "%w/w"}:
        fraction = concentration / 100
        return fraction if 0 < fraction <= 1 else None
    if normalized in {"fraction", "massfraction", "weightfraction", "w/w"}:
        return concentration if 0 < concentration <= 1 else None
    return None


def normalized_concentration_units(units: str | None) -> str:
    if not units:
        return ""
    text = str(units).strip().lower()
    text = text.replace(chr(956), "u").replace(chr(181), "u").replace(chr(8722), "-")
    text = text.replace(" per ", "/").replace(" / ", "/")
    return text.replace(" ", "").replace(".", "")


def numeric_fraction_value(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if 0 < number <= 1 else None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    if text.endswith("%"):
        try:
            percentage = float(text[:-1].strip())
        except ValueError:
            return None
        fraction = percentage / 100
        return fraction if 0 < fraction <= 1 else None
    number = numeric_value(text)
    return number if number is not None and 0 < number <= 1 else None


def numeric_value(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    token = text.split()[0]
    try:
        return float(token)
    except ValueError:
        return None


def material_audit_recommendations(
    missing_required: list[str],
    quantity_gaps: list[dict[str, Any]],
    property_gaps: list[dict[str, Any]],
) -> list[str]:
    recommendations = []
    if missing_required:
        recommendations.append(
            "Add formulation rows for missing required material groups: "
            + ", ".join(missing_required)
            + "."
        )
    if quantity_gaps:
        recommendations.append(
            "Enter at least one quantitative basis for every formulation row: mass_g, volume_mL, moles_mmol, wt_percent, or concentration."
        )
    if property_gaps:
        recommendations.append(
            "Complete Master Reagents physical-property fields needed for calculations, especially molecular weight and density for monomers."
        )
    if not recommendations:
        recommendations.append("Material role and quantitative fields are sufficient for a first-pass agent recommendation.")
    return recommendations


def material_audit_summary(
    missing_required: list[str],
    quantity_gaps: list[dict[str, Any]],
    property_gaps: list[dict[str, Any]],
) -> str:
    if not missing_required and not quantity_gaps and not property_gaps:
        return "Material scaffold is complete enough for first-pass experiment planning."
    parts = []
    if missing_required:
        parts.append(f"missing required groups: {', '.join(missing_required)}")
    if quantity_gaps:
        parts.append(f"{len(quantity_gaps)} formulation rows lack quantitative basis")
    if property_gaps:
        parts.append(f"{len(property_gaps)} formulation rows have reagent property gaps")
    return "Material scaffold needs attention: " + "; ".join(parts) + "."


def nonblank(value: Any) -> bool:
    return value is not None and str(value).strip() != ""
