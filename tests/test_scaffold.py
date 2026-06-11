from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from lab_notebook_agent.agent import (
    AgentRunConfig,
    build_agent_report,
    notebook_context_matches,
    run_workbook_agent,
    selected_experiment_ids,
)
from lab_notebook_agent.daily_summary import build_daily_summary_report
from lab_notebook_agent.daily_agent import build_daily_agent_run, build_snapshot_daily_agent_run, run_workbook_daily_agent
from lab_notebook_agent.daily_log_results import (
    apply_daily_log_results_report_to_workbook,
    build_daily_log_results_report,
)
from lab_notebook_agent.formulation_normalization import (
    apply_formulation_normalization_report_to_workbook,
    build_formulation_normalization_report,
)
from lab_notebook_agent.google_sheets import (
    audit_report_against_snapshot,
    batch_update_requests_from_report,
    sheet_ids_from_snapshot,
    snapshot_capture_plan,
    snapshot_from_tables,
    snapshot_to_tables,
    validate_snapshot,
)
from lab_notebook_agent.google_api import (
    capture_snapshot_from_google_sheets,
    google_api_doctor,
    run_live_google_daily_agent,
    run_live_google_daily_log_results_normalization,
    run_live_google_agent,
    run_live_google_formulation_normalization,
    run_live_google_plan_materialization,
)
from lab_notebook_agent.cli import main, parse_sheet_id_args
from lab_notebook_agent.litscout import evidence_rows_to_values, litscout_works_to_evidence_rows
from lab_notebook_agent.material_scaffold import (
    apply_material_scaffold_report_to_workbook,
    build_material_scaffold_report,
)
from lab_notebook_agent.material_search import build_process_material_search_report
from lab_notebook_agent.materials import audit_experiment_materials, calculate_formulation_row
from lab_notebook_agent.notebook_search import search_notebook_tables
from lab_notebook_agent.planning import (
    apply_plan_materialization_report_to_workbook,
    build_plan_materialization_report,
)
from lab_notebook_agent.preflight import build_experiment_preflight_report
from lab_notebook_agent.recommend import build_recommendation, load_entry
from lab_notebook_agent.schema import SHEETS, workbook_contract
from lab_notebook_agent.search import LocalSemanticIndex
from lab_notebook_agent.sheets import (
    append_suggestion_to_workbook,
    build_experiment_entry_from_tables,
    load_workbook_tables,
    rows_from_values,
    suggestion_to_values,
    suggest_from_workbook,
)
from lab_notebook_agent.templates import save_workbook


class ScaffoldTests(unittest.TestCase):
    def test_workbook_template_contains_contract_tabs_and_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = save_workbook(Path(tmpdir) / "template.xlsx")
            workbook = load_workbook(output)
            self.assertEqual([sheet.name for sheet in SHEETS], workbook.sheetnames)
            for spec in SHEETS:
                worksheet = workbook[spec.name]
                headers = [cell.value for cell in worksheet[1]]
                self.assertEqual(list(spec.headers), headers)

    def test_semantic_search_finds_emulsion_polymerization_material_roles(self) -> None:
        results = LocalSemanticIndex.from_default().search(
            "emulsion polymerization monomers initiator surfactant particle size",
            k=2,
        )
        self.assertTrue(results)
        self.assertIn("emulsion polymerization", results[0].record["process_type"])

    def test_notebook_search_finds_reagents_and_process_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            result = search_notebook_tables(
                load_workbook_tables(workbook_path),
                "emulsion polymerization surfactant particle size latex stability",
                k=8,
            )
            self.assertGreater(result["summary"]["records_indexed"], 0)
            sheets = {row["sheet"] for row in result["results"]}
            self.assertIn("Master Reagents", sheets)
            self.assertIn("Process Knowledge", sheets)
            self.assertTrue(
                any(row["key_fields"].get("reagent_id") == "S-SDS" for row in result["results"]),
                result["results"],
            )

    def test_process_material_search_groups_emulsion_reagent_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tables = load_workbook_tables(save_workbook(Path(tmpdir) / "template.xlsx"))
            report = build_process_material_search_report(
                tables,
                process_type="emulsion polymerization",
                experiment_id="EP-001",
            )
            self.assertEqual("lab-notebook-agent-process-material-search.v1", report["schema"])
            self.assertEqual(4, report["summary"]["role_group_count"])
            self.assertEqual([], report["summary"]["required_roles_missing_candidates"])
            roles = {row["role_group"]: row for row in report["roles"]}
            self.assertEqual("M-SKA", roles["monomer"]["candidate_reagents"][0]["reagent_id"])
            self.assertEqual("I-APS", roles["initiator"]["candidate_reagents"][0]["reagent_id"])
            self.assertEqual("S-SDS", roles["surfactant"]["candidate_reagents"][0]["reagent_id"])
            self.assertEqual("present_in_formulation", roles["monomer"]["status"])
            self.assertEqual("optional_no_candidate", roles["aqueous_phase"]["status"])
            self.assertIn("molecular_weight_g_mol", roles["monomer"]["candidate_reagents"][0]["missing_important_fields"])
            self.assertTrue(roles["surfactant"]["process_knowledge_matches"])

    def test_process_material_search_can_include_optional_roles(self) -> None:
        report = build_process_material_search_report(
            {"Master Reagents": [], "Process Knowledge": []},
            process_type="emulsion polymerization",
            include_optional=True,
        )
        roles = {row["role_group"]: row for row in report["roles"]}
        self.assertIn("crosslinker_or_chain_transfer", roles)
        self.assertEqual("optional_no_candidate", roles["crosslinker_or_chain_transfer"]["status"])

    def test_notebook_search_can_filter_to_daily_log_from_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tables = load_workbook_tables(save_workbook(Path(tmpdir) / "template.xlsx"))
            snapshot = snapshot_from_tables(tables)
            result = search_notebook_tables(
                snapshot_to_tables(snapshot),
                "coagulum stir shaft particle size high",
                k=3,
                sheets=("Daily Log",),
            )
            self.assertEqual(["Daily Log"], result["searched_sheets"])
            self.assertEqual("Daily Log", result["results"][0]["sheet"])
            self.assertEqual("EP-001", result["results"][0]["key_fields"]["experiment_id"])

    def test_workbook_contract_matches_sheet_specs(self) -> None:
        contract = workbook_contract()
        sheet_names = [sheet["name"] for sheet in contract["sheets"]]
        self.assertEqual([sheet.name for sheet in SHEETS], sheet_names)
        self.assertIn("emulsion polymerization", contract["controlled_vocab"]["process_type"])

    def test_suggestion_includes_litscout_commands(self) -> None:
        entry = load_entry(Path(__file__).parents[1] / "examples/emulsion_polymerization_entry.json")
        suggestion = build_recommendation(entry)
        self.assertEqual("EP-001", suggestion["experiment_id"])
        self.assertIn("surfactant", suggestion["proposed_change"].lower())
        self.assertEqual(2, len(suggestion["litscout"]["commands"]))
        self.assertIn("litscout search multi", suggestion["litscout"]["commands"][0])
        self.assertIn("material_audit", suggestion)
        self.assertIn("proposed_experiment_plan", suggestion)

    def test_rows_from_values_drops_blank_rows_and_preserves_headers(self) -> None:
        rows = rows_from_values(
            [
                ["experiment_id", "objective"],
                ["EP-001", "Reduce particle size"],
                ["", ""],
            ]
        )
        self.assertEqual([{"experiment_id": "EP-001", "objective": "Reduce particle size"}], rows)

    def test_workbook_tabs_assemble_experiment_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            tables = load_workbook_tables(workbook_path)
            entry = build_experiment_entry_from_tables(tables, "EP-001")
            self.assertEqual("EP-001", entry["experiment_id"])
            self.assertEqual("emulsion polymerization", entry["process_type"])
            self.assertEqual(3, len(entry["formulation"]))
            self.assertEqual("solketal acrylate", entry["formulation"][0]["reagent_name"])

    def test_material_audit_detects_emulsion_roles_and_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            entry = build_experiment_entry_from_tables(load_workbook_tables(workbook_path), "EP-001")
            audit = audit_experiment_materials(entry)
            groups = {group["role_group"]: group for group in audit["role_groups"]}
            self.assertEqual("present", groups["monomer"]["status"])
            self.assertEqual("present", groups["initiator"]["status"])
            self.assertEqual("present", groups["surfactant"]["status"])
            self.assertFalse(audit["ready_for_quantitative_suggestion"])
            self.assertEqual(3, len(audit["quantity_gaps"]))
            self.assertTrue(any(gap["reagent_id"] == "M-SKA" for gap in audit["reagent_property_gaps"]))

    def test_material_audit_accepts_quantified_entry(self) -> None:
        entry = load_entry(Path(__file__).parents[1] / "examples/emulsion_polymerization_entry.json")
        entry["formulation"][0]["mass_g"] = 10
        entry["formulation"][0]["reagent_molecular_weight_g_mol"] = 156.18
        entry["formulation"][0]["reagent_density_g_mL"] = 1.05
        entry["formulation"][1]["mass_g"] = 0.2
        entry["formulation"][1]["reagent_molecular_weight_g_mol"] = 288.38
        entry["formulation"][1]["concentration"] = "active mass"
        entry["formulation"][2]["mass_g"] = 0.1
        entry["formulation"][2]["reagent_molecular_weight_g_mol"] = 228.2
        audit = audit_experiment_materials(entry)
        self.assertTrue(audit["ready_for_quantitative_suggestion"], audit)
        self.assertEqual([], audit["quantity_gaps"])
        monomer_calc = audit["formulation_calculations"][0]
        self.assertAlmostEqual(64.028685, monomer_calc["derived"]["moles_mmol"], places=4)
        self.assertAlmostEqual(9.52381, monomer_calc["derived"]["volume_mL"], places=4)

    def test_experiment_preflight_flags_incomplete_template_material_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            report = build_experiment_preflight_report(
                load_workbook_tables(workbook_path),
                experiment_id="EP-001",
                stage="review",
            )
            self.assertEqual("needs_attention", report["status"])
            self.assertFalse(report["ready_to_run"])
            self.assertFalse(report["ready_for_quantitative_suggestion"])
            checks = {row["name"]: row for row in report["checks"]}
            self.assertEqual("fail", checks["formulation_quantities"]["status"])
            self.assertEqual("fail", checks["reagent_properties"]["status"])
            self.assertEqual("pass", checks["daily_log_observations"]["status"])
            self.assertEqual("pass", checks["results_measurements"]["status"])

    def test_experiment_preflight_passes_completed_review_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            tables = load_workbook_tables(workbook_path)
            for row in tables["Master Reagents"]:
                if row["reagent_id"] == "M-SKA":
                    row["molecular_weight_g_mol"] = "156.18"
                    row["density_g_mL"] = "1.05"
                if row["reagent_id"] == "S-SDS":
                    row["concentration"] = "active mass"
            for row in tables["Formulations"]:
                if row["reagent_id"] == "M-SKA":
                    row["mass_g"] = "10"
                if row["reagent_id"] == "I-APS":
                    row["mass_g"] = "0.2"
                if row["reagent_id"] == "S-SDS":
                    row["mass_g"] = "0.1"
            report = build_experiment_preflight_report(tables, experiment_id="EP-001", stage="review")
            self.assertEqual("ready_with_warnings", report["status"])
            self.assertTrue(report["ready_to_run"])
            self.assertTrue(report["ready_for_quantitative_suggestion"])
            self.assertTrue(report["ready_for_agent_suggestion"])
            checks = {row["name"]: row for row in report["checks"]}
            self.assertEqual("warn", checks["literature_evidence"]["status"])
            self.assertEqual("pass", checks["reagent_properties"]["status"])

    def test_formulation_calculation_derives_mass_and_moles_from_volume(self) -> None:
        calculation = calculate_formulation_row(
            {
                "reagent_id": "M-TEST",
                "target_role": "core_monomer",
                "volume_mL": "2.0",
                "reagent_density_g_mL": "1.05",
                "reagent_molecular_weight_g_mol": "156.18",
            }
        )
        self.assertAlmostEqual(2.1, calculation["derived"]["mass_g"], places=6)
        self.assertAlmostEqual(13.446, calculation["derived"]["moles_mmol"], places=3)
        self.assertEqual([], calculation["missing_for_calculations"])

    def test_formulation_normalization_derives_missing_cells(self) -> None:
        tables = {
            "Master Reagents": [
                {"reagent_id": "M-SKA", "molecular_weight_g_mol": "156.18", "density_g_mL": "1.05"},
            ],
            "Formulations": [
                {
                    "experiment_id": "EP-001",
                    "reagent_id": "M-SKA",
                    "phase": "monomer feed",
                    "target_role": "core_monomer",
                    "mass_g": "10",
                    "volume_mL": "",
                    "moles_mmol": "",
                }
            ],
        }
        report = build_formulation_normalization_report(tables, experiment_ids=("EP-001",))
        self.assertEqual("lab-notebook-agent-formulation-normalization.v1", report["schema"])
        self.assertEqual(2, report["summary"]["formulation_cells_to_update"])
        updates = {row["field"]: row["value"] for row in report["runs"][0]["update_formulations"]}
        self.assertEqual("9.52381", updates["volume_mL"])
        self.assertEqual("64.028685", updates["moles_mmol"])

    def test_formulation_normalization_apply_writes_updates_to_workbook(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            workbook = load_workbook(workbook_path)
            workbook["Master Reagents"]["F2"] = "156.18"
            workbook["Master Reagents"]["G2"] = "1.05"
            workbook["Formulations"]["E2"] = "10"
            workbook.save(workbook_path)
            output_path = Path(tmpdir) / "normalized.xlsx"
            report = build_formulation_normalization_report(
                load_workbook_tables(workbook_path),
                experiment_ids=("EP-001",),
            )
            apply_formulation_normalization_report_to_workbook(workbook_path, report, output_path)
            normalized = load_workbook(output_path)
            self.assertEqual("9.52381", normalized["Formulations"]["F2"].value)
            self.assertEqual("64.028685", normalized["Formulations"]["G2"].value)

    def test_formulation_normalization_snapshot_emits_google_batch_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            workbook = load_workbook(workbook_path)
            workbook["Master Reagents"]["F2"] = "156.18"
            workbook["Master Reagents"]["G2"] = "1.05"
            workbook["Formulations"]["E2"] = "10"
            workbook.save(workbook_path)
            snapshot = snapshot_from_tables(load_workbook_tables(workbook_path), {"Formulations": 103})
            report = build_formulation_normalization_report(snapshot_to_tables(snapshot), experiment_ids=("EP-001",))
            audit = audit_report_against_snapshot(report, snapshot)
            self.assertTrue(audit["valid"], audit["errors"])
            self.assertEqual(2, audit["summary"]["formulation_cells_to_update"])
            requests = batch_update_requests_from_report(report, sheet_ids_from_snapshot(snapshot))
            self.assertEqual(2, len(requests))
            self.assertEqual(103, requests[0]["updateCells"]["start"]["sheetId"])
            self.assertEqual(5, requests[0]["updateCells"]["start"]["columnIndex"])
            self.assertEqual(6, requests[1]["updateCells"]["start"]["columnIndex"])

    def test_suggestion_maps_to_agent_suggestions_row(self) -> None:
        entry = load_entry(Path(__file__).parents[1] / "examples/emulsion_polymerization_entry.json")
        suggestion = build_recommendation(entry)
        values = suggestion_to_values(suggestion)
        self.assertEqual(13, len(values))
        self.assertEqual("EP-001", values[2])
        self.assertEqual("EP-001-FUP-001", values[8])
        self.assertIn("surfactant_package", values[9])
        self.assertIn("formulations", values[9])
        self.assertEqual("draft", values[-1])

    def test_append_suggestion_to_workbook(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            entry = load_entry(Path(__file__).parents[1] / "examples/emulsion_polymerization_entry.json")
            suggestion = build_recommendation(entry)
            output_path = append_suggestion_to_workbook(
                workbook_path,
                suggestion,
                Path(tmpdir) / "with-suggestion.xlsx",
            )
            workbook = load_workbook(output_path)
            worksheet = workbook["Agent Suggestions"]
            self.assertEqual("EP-001", worksheet["C2"].value)
            self.assertEqual("EP-001-FUP-001", worksheet["I2"].value)
            self.assertIn("surfactant_package", worksheet["J2"].value)
            self.assertIn("formulations", worksheet["J2"].value)
            self.assertEqual("draft", worksheet["M2"].value)

    def test_suggest_from_workbook_uses_joined_tab_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            suggestion = suggest_from_workbook(workbook_path, "EP-001")
        self.assertEqual("EP-001", suggestion["experiment_id"])
        self.assertIn("particle-size", suggestion["expected_effect"])

    def test_material_scaffold_generates_emulsion_starter_placeholders(self) -> None:
        report = build_material_scaffold_report(
            {"Master Reagents": [], "Formulations": []},
            experiment_id="EP-NEW",
            process_type="emulsion polymerization",
        )
        self.assertEqual(4, report["summary"]["role_groups_considered"])
        self.assertEqual(4, report["summary"]["master_reagent_rows_to_append"])
        self.assertEqual(4, report["summary"]["formulation_rows_to_append"])
        roles = {row["target_role"] for row in report["append_formulations"]}
        self.assertIn("core_monomer", roles)
        self.assertIn("initiator", roles)
        self.assertIn("surfactant", roles)
        self.assertIn("solvent", roles)

    def test_material_scaffold_reuses_existing_master_reagents(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            report = build_material_scaffold_report(
                load_workbook_tables(workbook_path),
                experiment_id="EP-002",
                process_type="emulsion polymerization",
            )
            self.assertEqual(1, report["summary"]["master_reagent_rows_to_append"])
            self.assertEqual(4, report["summary"]["formulation_rows_to_append"])
            reagent_ids = {row["reagent_id"] for row in report["append_formulations"]}
            self.assertIn("M-SKA", reagent_ids)
            self.assertIn("I-APS", reagent_ids)
            self.assertIn("S-SDS", reagent_ids)

            output_path = Path(tmpdir) / "scaffolded.xlsx"
            apply_material_scaffold_report_to_workbook(workbook_path, report, output_path)
            workbook = load_workbook(output_path)
            self.assertEqual("EP-002", workbook["Formulations"]["A5"].value)

    def test_material_scaffold_snapshot_emits_google_batch_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            snapshot = snapshot_from_tables(
                load_workbook_tables(workbook_path),
                {
                    "Master Reagents": 100,
                    "Formulations": 103,
                    "Literature Evidence": 111,
                    "Agent Suggestions": 222,
                },
            )
            report = build_material_scaffold_report(
                snapshot_to_tables(snapshot),
                experiment_id="EP-002",
                process_type="emulsion polymerization",
            )
            audit = audit_report_against_snapshot(report, snapshot)
            self.assertTrue(audit["valid"], audit["errors"])
            requests = batch_update_requests_from_report(report, sheet_ids_from_snapshot(snapshot))
            self.assertEqual(2, len(requests))
            self.assertEqual(100, requests[0]["appendCells"]["sheetId"])
            self.assertEqual(103, requests[1]["appendCells"]["sheetId"])

    def test_litscout_export_maps_to_literature_evidence_rows(self) -> None:
        works = [
            {
                "title": "Role of anionic and nonionic surfactants on particle size",
                "service": "openalex",
                "author_names": ["A. Author", "B. Author"],
                "year": 2006,
                "doi": "10.1002/app.23717",
                "url": "https://doi.org/10.1002/app.23717",
                "cited_by_count": 10,
                "concepts": [
                    {"display_name": "Emulsion polymerization"},
                    {"display_name": "Particle size"},
                    {"display_name": "Surfactant"},
                ],
            }
        ]
        rows = litscout_works_to_evidence_rows(
            works,
            experiment_id="EP-001",
            query="emulsion polymerization surfactant particle size",
        )
        self.assertEqual("LIT-EP-001-001", rows[0]["evidence_id"])
        self.assertIn("particle_size", rows[0]["relevance_tags"])
        self.assertEqual(11, len(evidence_rows_to_values(rows)[0]))

    def test_recommendation_links_literature_evidence_ids(self) -> None:
        entry = load_entry(Path(__file__).parents[1] / "examples/emulsion_polymerization_entry.json")
        entry["literature_evidence"] = [
            {
                "evidence_id": "LIT-EP-001-001",
                "title": "Surfactant control of emulsion polymer particle size",
                "finding": "Surfactant package can affect particle size and colloidal stability.",
                "relevance_tags": "surfactant,particle_size,stability",
                "confidence": "medium",
            }
        ]
        suggestion = build_recommendation(entry)
        self.assertEqual(["LIT-EP-001-001"], suggestion["linked_evidence_ids"])
        self.assertIn("Literature Evidence rows", suggestion["rationale"])
        self.assertIn("Linked literature tags emphasize", suggestion["rationale"])
        self.assertIn("Literature guidance", suggestion["rationale"])
        self.assertEqual(1, suggestion["literature_context"]["evidence_count"])
        self.assertEqual(1, suggestion["literature_context"]["tag_counts"]["surfactant"])
        self.assertIn("particle_size", suggestion["literature_context"]["relevance_tags"])
        self.assertEqual(["LIT-EP-001-001"], suggestion["proposed_experiment_plan"]["linked_evidence_ids"])
        support = suggestion["proposed_experiment_plan"]["literature_support"]
        self.assertEqual(["LIT-EP-001-001"], support["evidence_ids"])
        self.assertTrue(support["guidance"])

    def test_recommendation_infers_literature_tags_from_findings(self) -> None:
        entry = load_entry(Path(__file__).parents[1] / "examples/emulsion_polymerization_entry.json")
        entry["literature_evidence"] = [
            {
                "evidence_id": "LIT-EP-001-002",
                "title": "Semibatch monomer feed and latex nucleation",
                "finding": "Feed profile changes affected particle size in acrylate latex experiments.",
            }
        ]
        suggestion = build_recommendation(entry)
        context = suggestion["literature_context"]
        self.assertIn("feed", context["relevance_tags"])
        self.assertIn("particle_size", context["relevance_tags"])
        self.assertIn("feed/nucleation", " ".join(context["guidance"]))
        self.assertEqual("LIT-EP-001-002", context["supporting_findings"][0]["evidence_id"])

    def test_structured_emulsion_plan_has_variables_and_capture_fields(self) -> None:
        entry = load_entry(Path(__file__).parents[1] / "examples/emulsion_polymerization_entry.json")
        suggestion = build_recommendation(entry)
        plan = suggestion["proposed_experiment_plan"]
        self.assertEqual("EP-001-FUP-001", plan["suggested_experiment_id"])
        factors = [variable["factor"] for variable in plan["variables"]]
        self.assertIn("surfactant_active_basis_or_feed_duration", factors)
        self.assertIn("surfactant_package", factors)
        self.assertIn("particle_size_nm", plan["measurements"])
        self.assertTrue(plan["prerequisites"])
        self.assertEqual("planned", plan["sheet_rows"]["experiments"][0]["status"])

    def test_agent_report_appends_evidence_and_linked_suggestion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            works_path = write_fake_litscout_export(Path(tmpdir) / "works.json")
            tables = load_workbook_tables(workbook_path)
            report = build_agent_report(
                tables,
                AgentRunConfig(experiment_ids=("EP-001",), litscout_export=str(works_path)),
            )
            self.assertEqual("ready", report["runs"][0]["status"])
            self.assertEqual(1, report["summary"]["suggestion_rows_to_append"])
            self.assertEqual(1, report["summary"]["evidence_rows_to_append"])
            suggestion = report["runs"][0]["append_agent_suggestions"][0]
            self.assertEqual(["LIT-EP-001-001"], suggestion["linked_evidence_ids"])
            self.assertEqual("loaded_export", report["runs"][0]["litscout_status"]["status"])
            self.assertEqual(1, report["runs"][0]["litscout_status"]["works_count"])
            context_sheets = {row["sheet"] for row in report["runs"][0]["notebook_context_matches"]}
            self.assertIn("Master Reagents", context_sheets)
            self.assertIn("Process Knowledge", context_sheets)

    def test_agent_report_includes_prior_result_history_in_suggestion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tables = load_workbook_tables(save_workbook(Path(tmpdir) / "template.xlsx"))
            tables["Experiments"].insert(
                0,
                {
                    "experiment_id": "EP-000",
                    "date": "2026-06-01",
                    "project": "SABER CCSP",
                    "process_type": "emulsion polymerization",
                    "objective": "Baseline particle size screen.",
                    "status": "complete",
                    "summary": "Lower particle size but stable latex.",
                },
            )
            tables["Results"].append(
                {
                    "experiment_id": "EP-000",
                    "sample_id": "EP-000-L1",
                    "measurement_type": "DLS particle size",
                    "value": "240",
                    "units": "nm",
                    "quality_flag": "ok",
                    "interpretation": "Within target range.",
                }
            )
            report = build_agent_report(
                tables,
                AgentRunConfig(experiment_ids=("EP-001",)),
            )
            run = report["runs"][0]
            self.assertEqual(1, run["historical_context"]["prior_experiment_count"])
            self.assertIn("EP-000", run["historical_context"]["guidance"][0])
            benchmarks = {row["metric_key"]: row for row in run["historical_context"]["measurement_benchmarks"]}
            self.assertEqual("240", benchmarks["particle_size"]["min"])
            suggestion = run["append_agent_suggestions"][0]
            self.assertIn("Notebook history", suggestion["rationale"])
            self.assertEqual(1, suggestion["historical_context"]["prior_experiment_count"])
            self.assertEqual("EP-000", suggestion["proposed_experiment_plan"]["history_support"]["prior_experiments"][0]["experiment_id"])

    def test_agent_run_cli_history_limit_can_disable_prior_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            workbook = load_workbook(workbook_path)
            experiments = workbook["Experiments"]
            experiments.append(
                [
                    "EP-000",
                    "2026-06-01",
                    "SABER CCSP",
                    "emulsion polymerization",
                    "Baseline particle size screen.",
                    "",
                    "",
                    "",
                    "complete",
                    "",
                    "Lower particle size but stable latex.",
                ]
            )
            workbook["Results"].append(
                [
                    "EP-000",
                    "EP-000-L1",
                    "DLS particle size",
                    "intensity average",
                    "240",
                    "nm",
                    "post-feed",
                    "1",
                    "ok",
                    "Within target range.",
                ]
            )
            workbook.save(workbook_path)
            output = Path(tmpdir) / "agent-report.json"
            with patch("builtins.print"):
                exit_code = main(
                    [
                        "agent-run",
                        "--workbook",
                        str(workbook_path),
                        "--experiment-id",
                        "EP-001",
                        "--history-limit",
                        "0",
                        "--report-output",
                        str(output),
                    ]
                )
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(0, exit_code)
            self.assertEqual(0, report["runs"][0]["historical_context"]["prior_experiment_count"])
            suggestion = report["runs"][0]["append_agent_suggestions"][0]
            self.assertEqual(0, suggestion["proposed_experiment_plan"]["history_support"]["prior_experiment_count"])

    def test_agent_report_can_run_litscout_and_records_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            calls = []

            def fake_run(command: list[str], check: bool) -> None:
                calls.append(command)
                if command[:3] == ["litscout", "sessions", "export"]:
                    output_path = Path(command[command.index("--output") + 1])
                    write_fake_litscout_export(output_path)

            with patch("lab_notebook_agent.agent.subprocess.run", side_effect=fake_run):
                report = build_agent_report(
                    load_workbook_tables(workbook_path),
                    AgentRunConfig(
                        experiment_ids=("EP-001",),
                        run_litscout=True,
                        artifacts_dir=tmpdir,
                    ),
                )

            run = report["runs"][0]
            self.assertEqual("ready", run["status"])
            self.assertEqual("completed", run["litscout_status"]["status"])
            self.assertEqual(1, run["litscout_status"]["works_count"])
            self.assertTrue(run["litscout_export"].endswith("litscout-ep-001.json"))
            self.assertEqual(1, report["summary"]["evidence_rows_to_append"])
            self.assertEqual(2, len(calls))
            self.assertEqual(["litscout", "search", "multi"], calls[0][:3])

    def test_agent_report_records_litscout_failure_without_suggestion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            with patch("lab_notebook_agent.agent.subprocess.run", side_effect=FileNotFoundError()):
                report = build_agent_report(
                    load_workbook_tables(workbook_path),
                    AgentRunConfig(
                        experiment_ids=("EP-001",),
                        run_litscout=True,
                        artifacts_dir=tmpdir,
                    ),
                )

            run = report["runs"][0]
            self.assertEqual("skipped", run["status"])
            self.assertEqual("litscout_failed", run["skip_reason"])
            self.assertEqual("failed", run["litscout_status"]["status"])
            self.assertEqual("FileNotFoundError", run["litscout_status"]["error_type"])
            self.assertEqual([], run["append_agent_suggestions"])
            self.assertEqual(1, report["summary"]["litscout_failures"])
            self.assertEqual(0, report["summary"]["suggestion_rows_to_append"])

    def test_agent_report_records_litscout_command_failure_without_suggestion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            failure = subprocess.CalledProcessError(2, ["litscout", "search", "multi"])
            with patch("lab_notebook_agent.agent.subprocess.run", side_effect=failure):
                report = build_agent_report(
                    load_workbook_tables(workbook_path),
                    AgentRunConfig(
                        experiment_ids=("EP-001",),
                        run_litscout=True,
                        artifacts_dir=tmpdir,
                    ),
                )

            run = report["runs"][0]
            self.assertEqual("skipped", run["status"])
            self.assertEqual("litscout_failed", run["skip_reason"])
            self.assertEqual(2, run["litscout_status"]["returncode"])
            self.assertEqual("litscout search multi", run["litscout_status"]["command"])
            self.assertEqual(0, report["summary"]["suggestion_rows_to_append"])

    def test_notebook_context_filters_current_experiment_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tables = load_workbook_tables(save_workbook(Path(tmpdir) / "template.xlsx"))
            matches = notebook_context_matches(
                tables,
                "emulsion polymerization surfactant particle size coagulum",
                "EP-001",
                limit=5,
            )
            self.assertTrue(matches)
            self.assertFalse(
                any(row["sheet"] in {"Experiments", "Daily Log", "Formulations", "Results"} for row in matches),
                matches,
            )

    def test_agent_report_can_disable_notebook_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            works_path = write_fake_litscout_export(Path(tmpdir) / "works.json")
            report = build_agent_report(
                load_workbook_tables(workbook_path),
                AgentRunConfig(experiment_ids=("EP-001",), litscout_export=str(works_path), context_limit=0),
            )
            self.assertEqual([], report["runs"][0]["notebook_context_matches"])

    def test_daily_review_selects_experiments_by_date_and_log_timestamp(self) -> None:
        tables = {
            "Experiments": [
                {"experiment_id": "EP-001", "date": "2026-06-09", "status": "complete"},
                {"experiment_id": "EP-002", "date": "2026-06-08", "status": "complete"},
                {"experiment_id": "EP-003", "date": "2026-06-08", "status": "running"},
                {"experiment_id": "EP-004", "date": "2026-06-09", "status": "abandoned"},
            ],
            "Daily Log": [
                {"experiment_id": "EP-003", "timestamp": "2026-06-09T15:30:00"},
                {"experiment_id": "EP-002", "timestamp": "2026-06-08T09:00:00"},
                {"experiment_id": "EP-004", "timestamp": "2026-06-09T09:00:00"},
            ],
        }
        self.assertEqual(
            ["EP-001", "EP-003"],
            selected_experiment_ids(tables, (), review_date="2026-06-09"),
        )

    def test_agent_report_records_daily_review_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            works_path = write_fake_litscout_export(Path(tmpdir) / "works.json")
            report = build_agent_report(
                load_workbook_tables(workbook_path),
                AgentRunConfig(review_date="2026-06-09", litscout_export=str(works_path)),
            )
            self.assertEqual("2026-06-09", report["selection"]["review_date"])
            self.assertEqual(["EP-001"], report["selection"]["selected_experiment_ids"])
            self.assertEqual(1, report["summary"]["ready"])

    def test_daily_summary_reports_observations_results_and_material_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            report = build_daily_summary_report(
                load_workbook_tables(workbook_path),
                review_date="2026-06-09",
            )
            self.assertEqual("2026-06-09", report["review_date"])
            self.assertEqual(["EP-001"], report["selection"]["selected_experiment_ids"])
            self.assertEqual(1, report["summary"]["experiment_count"])
            self.assertEqual(1, report["summary"]["observation_count"])
            self.assertEqual(1, report["summary"]["result_count"])
            experiment = report["experiments"][0]
            self.assertIn("coagulum", experiment["issue_tags"])
            self.assertFalse(experiment["ready_for_quantitative_suggestion"])
            self.assertTrue(experiment["material_recommendations"])

    def test_daily_summary_includes_open_suggestions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            works_path = write_fake_litscout_export(Path(tmpdir) / "works.json")
            applied_path = Path(tmpdir) / "applied.xlsx"
            run_workbook_agent(
                workbook_path,
                AgentRunConfig(experiment_ids=("EP-001",), litscout_export=str(works_path)),
                apply=True,
                output_workbook=applied_path,
            )
            report = build_daily_summary_report(
                load_workbook_tables(applied_path),
                review_date="2026-06-09",
            )
            self.assertEqual(1, report["summary"]["open_suggestion_count"])
            self.assertEqual("draft", report["experiments"][0]["open_suggestions"][0]["status"])

    def test_daily_log_results_normalizes_structured_observations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            report = build_daily_log_results_report(
                load_workbook_tables(workbook_path),
                experiment_ids=("EP-001",),
            )
            self.assertEqual("lab-notebook-agent-daily-log-results.v1", report["schema"])
            self.assertEqual(1, report["summary"]["daily_log_rows_considered"])
            self.assertEqual(2, report["summary"]["result_rows_to_append"])
            self.assertEqual(1, report["summary"]["measurements_skipped"])
            rows = report["runs"][0]["append_results"]
            measurement_types = {row["measurement_type"] for row in rows}
            self.assertEqual({"temperature", "agitation speed"}, measurement_types)
            self.assertEqual("DLS particle size", report["runs"][0]["skipped_measurements"][0]["measurement_type"])

    def test_daily_log_results_extracts_measurements_from_observation_text(self) -> None:
        report = build_daily_log_results_report(
            {
                "Daily Log": [
                    {
                        "experiment_id": "EP-TEXT",
                        "timestamp": "2026-06-09T16:00:00",
                        "process_stage": "test",
                        "particle_size_nm": "510",
                        "observation": (
                            "DLS 510 nm after workup; conversion 76%; pH 5.8; "
                            "solids 39%; viscosity 120 cP; coagulum mass 0.4 g."
                        ),
                    }
                ],
                "Results": [],
            },
            experiment_ids=("EP-TEXT",),
        )
        rows = report["runs"][0]["append_results"]
        by_type = {row["measurement_type"]: row for row in rows}
        self.assertEqual(6, report["summary"]["result_rows_to_append"])
        self.assertEqual("510", by_type["DLS particle size"]["value"])
        self.assertEqual("Daily Log structured field", by_type["DLS particle size"]["method"])
        self.assertEqual("76", by_type["conversion"]["value"])
        self.assertEqual("5.8", by_type["pH"]["value"])
        self.assertEqual("39", by_type["solids percent"]["value"])
        self.assertEqual("120", by_type["viscosity"]["value"])
        self.assertEqual("0.4", by_type["coagulum mass"]["value"])
        self.assertTrue(all("observation text" in row["method"] for name, row in by_type.items() if name != "DLS particle size"))

    def test_daily_log_results_apply_writes_results_rows_to_workbook(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            output_path = Path(tmpdir) / "normalized.xlsx"
            report = build_daily_log_results_report(load_workbook_tables(workbook_path), experiment_ids=("EP-001",))
            apply_daily_log_results_report_to_workbook(workbook_path, report, output_path)
            workbook = load_workbook(output_path)
            worksheet = workbook["Results"]
            self.assertEqual("temperature", worksheet["C3"].value)
            self.assertEqual("70", worksheet["E3"].value)
            self.assertEqual("agitation speed", worksheet["C4"].value)

    def test_daily_log_results_snapshot_emits_google_batch_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            snapshot = snapshot_from_tables(
                load_workbook_tables(workbook_path),
                {"Results": 102},
            )
            report = build_daily_log_results_report(
                snapshot_to_tables(snapshot),
                experiment_ids=("EP-001",),
            )
            audit = audit_report_against_snapshot(report, snapshot)
            self.assertTrue(audit["valid"], audit["errors"])
            self.assertEqual(2, audit["summary"]["result_rows_to_append"])
            requests = batch_update_requests_from_report(report, sheet_ids_from_snapshot(snapshot))
            self.assertEqual(1, len(requests))
            self.assertEqual(102, requests[0]["appendCells"]["sheetId"])

    def test_daily_agent_run_combines_summary_and_agent_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            works_path = write_fake_litscout_export(Path(tmpdir) / "works.json")
            run = build_daily_agent_run(
                load_workbook_tables(workbook_path),
                AgentRunConfig(review_date="2026-06-09", litscout_export=str(works_path)),
            )
            self.assertEqual("lab-notebook-agent-daily-run.v1", run["schema"])
            self.assertEqual("2026-06-09", run["review_date"])
            self.assertEqual(["EP-001"], run["selection"]["selected_experiment_ids"])
            self.assertEqual(1, run["daily_summary"]["summary"]["experiment_count"])
            self.assertEqual(1, run["agent_report"]["summary"]["suggestion_rows_to_append"])
            self.assertEqual(1, run["summary"]["evidence_rows_to_append"])
            self.assertEqual(2, run["summary"]["normalized_result_rows_to_append"])
            self.assertEqual("lab-notebook-agent-daily-log-results.v1", run["daily_log_results_report"]["schema"])
            self.assertEqual(1, run["summary"]["experiment_review_count"])
            self.assertEqual(2, run["summary"]["preflight_fail_count"])
            review = run["experiment_reviews"][0]
            self.assertEqual("EP-001", review["experiment_id"])
            self.assertEqual("lab-notebook-agent-experiment-preflight.v1", review["preflight"]["schema"])
            self.assertEqual("lab-notebook-agent-process-material-search.v1", review["material_search"]["schema"])
            roles = {role["role_group"]: role for role in review["material_search"]["roles"]}
            self.assertEqual("M-SKA", roles["monomer"]["candidate_reagents"][0]["reagent_id"])

    def test_snapshot_daily_agent_run_includes_audit_and_batch_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            works_path = write_fake_litscout_export(Path(tmpdir) / "works.json")
            snapshot = snapshot_from_tables(
                load_workbook_tables(workbook_path),
                {"Experiments": 101, "Results": 102, "Literature Evidence": 111, "Agent Suggestions": 222, "Daily Reviews": 333},
            )
            run = build_snapshot_daily_agent_run(
                snapshot,
                AgentRunConfig(review_date="2026-06-09", litscout_export=str(works_path)),
            )
            self.assertTrue(run["snapshot_audit"]["valid"], run["snapshot_audit"])
            self.assertTrue(run["apply_audit"]["valid"], run["apply_audit"])
            self.assertEqual(1, len(run["experiment_reviews"]))
            self.assertEqual(1, run["apply_report"]["summary"]["daily_review_rows_to_append"])
            self.assertEqual(1, run["apply_audit"]["summary"]["daily_review_rows_to_append"])
            self.assertEqual(3, run["summary"]["experiment_cells_to_update"])
            self.assertEqual(3, run["apply_audit"]["summary"]["experiment_cells_to_update"])
            self.assertEqual(7, run["summary"]["apply_request_count"])
            self.assertEqual(102, run["batch_update_requests"][0]["appendCells"]["sheetId"])
            self.assertEqual(111, run["batch_update_requests"][1]["appendCells"]["sheetId"])
            self.assertEqual(222, run["batch_update_requests"][2]["appendCells"]["sheetId"])
            self.assertEqual(333, run["batch_update_requests"][3]["appendCells"]["sheetId"])
            self.assertEqual(101, run["batch_update_requests"][4]["updateCells"]["start"]["sheetId"])

    def test_daily_agent_apply_writes_daily_review_row_to_workbook(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            works_path = write_fake_litscout_export(Path(tmpdir) / "works.json")
            output_path = Path(tmpdir) / "daily-applied.xlsx"
            run_workbook_daily_agent(
                workbook_path,
                AgentRunConfig(review_date="2026-06-09", litscout_export=str(works_path)),
                apply=True,
                output_workbook=output_path,
            )
            workbook = load_workbook(output_path)
            self.assertEqual("DRV-20260609-EP001", workbook["Daily Reviews"]["A2"].value)
            self.assertEqual("2026-06-09", workbook["Daily Reviews"]["C2"].value)
            self.assertEqual("needs_attention", workbook["Daily Reviews"]["N2"].value)
            self.assertEqual("needs_review", workbook["Experiments"]["I2"].value)
            self.assertIn("Daily review 2026-06-09", workbook["Experiments"]["K2"].value)

    def test_agent_run_apply_writes_evidence_and_suggestion_to_workbook(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            works_path = write_fake_litscout_export(Path(tmpdir) / "works.json")
            output_path = Path(tmpdir) / "applied.xlsx"
            run_workbook_agent(
                workbook_path,
                AgentRunConfig(experiment_ids=("EP-001",), litscout_export=str(works_path)),
                apply=True,
                output_workbook=output_path,
            )
            workbook = load_workbook(output_path)
            self.assertEqual("LIT-EP-001-001", workbook["Literature Evidence"]["A2"].value)
            self.assertEqual("EP-001", workbook["Agent Suggestions"]["C2"].value)
            self.assertEqual("LIT-EP-001-001", workbook["Agent Suggestions"]["H2"].value)
            self.assertEqual("EP-001-FUP-001", workbook["Agent Suggestions"]["I2"].value)

    def test_agent_report_skips_existing_suggestion_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            works_path = write_fake_litscout_export(Path(tmpdir) / "works.json")
            output_path = Path(tmpdir) / "applied.xlsx"
            run_workbook_agent(
                workbook_path,
                AgentRunConfig(experiment_ids=("EP-001",), litscout_export=str(works_path)),
                apply=True,
                output_workbook=output_path,
            )
            report = run_workbook_agent(
                output_path,
                AgentRunConfig(experiment_ids=("EP-001",), litscout_export=str(works_path)),
            )
            self.assertEqual("skipped", report["runs"][0]["status"])
            self.assertEqual("existing_suggestion", report["runs"][0]["skip_reason"])

    def test_google_batch_requests_from_agent_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            works_path = write_fake_litscout_export(Path(tmpdir) / "works.json")
            report = run_workbook_agent(
                workbook_path,
                AgentRunConfig(experiment_ids=("EP-001",), litscout_export=str(works_path)),
            )
            requests = batch_update_requests_from_report(
                report,
                {"Literature Evidence": 111, "Agent Suggestions": 222},
            )
            self.assertEqual(2, len(requests))
            self.assertEqual(111, requests[0]["appendCells"]["sheetId"])
            self.assertEqual(222, requests[1]["appendCells"]["sheetId"])
            self.assertEqual("EP-001", requests[1]["appendCells"]["rows"][0]["values"][2]["userEnteredValue"]["stringValue"])

    def test_snapshot_round_trip_drives_agent_report_and_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            works_path = write_fake_litscout_export(Path(tmpdir) / "works.json")
            tables = load_workbook_tables(workbook_path)
            snapshot = snapshot_from_tables(
                tables,
                {"Literature Evidence": 111, "Agent Suggestions": 222},
            )
            report = build_agent_report(
                snapshot_to_tables(snapshot),
                AgentRunConfig(experiment_ids=("EP-001",), litscout_export=str(works_path)),
            )
            requests = batch_update_requests_from_report(report, sheet_ids_from_snapshot(snapshot))
            self.assertEqual(1, report["summary"]["suggestion_rows_to_append"])
            self.assertEqual(2, len(requests))
            self.assertEqual("LIT-EP-001-001", requests[0]["appendCells"]["rows"][0]["values"][0]["userEnteredValue"]["stringValue"])

    def test_parse_sheet_id_args(self) -> None:
        self.assertEqual(
            {"Literature Evidence": 111, "Agent Suggestions": 222},
            parse_sheet_id_args(["Literature Evidence=111", "Agent Suggestions=222"]),
        )

    def test_google_capture_plan_lists_all_contract_sheets(self) -> None:
        plan = snapshot_capture_plan("spreadsheet-123")
        self.assertEqual("spreadsheet-123", plan["spreadsheet_id"])
        self.assertEqual([sheet.name for sheet in SHEETS], [row["sheet_name"] for row in plan["sheets"]])
        apply_sheets = [row["sheet_name"] for row in plan["sheets"] if row["used_for_apply"]]
        self.assertEqual(
            ["Master Reagents", "Experiments", "Formulations", "Results", "Literature Evidence", "Agent Suggestions", "Daily Reviews"],
            apply_sheets,
        )

    def test_validate_snapshot_detects_header_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tables = load_workbook_tables(save_workbook(Path(tmpdir) / "template.xlsx"))
            snapshot = snapshot_from_tables(tables)
            snapshot["sheets"]["Experiments"]["values"][0][0] = "bad_header"
            audit = validate_snapshot(snapshot)
            self.assertFalse(audit["valid"])
            self.assertEqual("header_mismatch", audit["errors"][0]["code"])

    def test_audit_report_against_snapshot_detects_duplicate_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            works_path = write_fake_litscout_export(Path(tmpdir) / "works.json")
            applied_path = Path(tmpdir) / "applied.xlsx"
            report = run_workbook_agent(
                workbook_path,
                AgentRunConfig(experiment_ids=("EP-001",), litscout_export=str(works_path)),
                apply=True,
                output_workbook=applied_path,
            )
            snapshot = snapshot_from_tables(
                load_workbook_tables(applied_path),
                {"Literature Evidence": 111, "Agent Suggestions": 222},
            )
            audit = audit_report_against_snapshot(report, snapshot)
            self.assertFalse(audit["valid"])
            self.assertTrue(any(error["code"] == "duplicate_append" for error in audit["errors"]))

    def test_audit_report_accepts_target_sheet_ids_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            works_path = write_fake_litscout_export(Path(tmpdir) / "works.json")
            report = run_workbook_agent(
                workbook_path,
                AgentRunConfig(experiment_ids=("EP-001",), litscout_export=str(works_path)),
            )
            snapshot = snapshot_from_tables(
                load_workbook_tables(workbook_path),
                {"Literature Evidence": 111, "Agent Suggestions": 222},
            )
            audit = audit_report_against_snapshot(report, snapshot)
            self.assertTrue(audit["valid"], audit["errors"])
            self.assertEqual(2, audit["summary"]["request_count"])

    def test_google_api_capture_snapshot_includes_live_sheet_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tables = load_workbook_tables(save_workbook(Path(tmpdir) / "template.xlsx"))
            client = FakeSheetsApiClient(
                snapshot_from_tables(
                    tables,
                    {
                        "Experiments": 101,
                        "Formulations": 103,
                        "Results": 102,
                        "Literature Evidence": 111,
                        "Agent Suggestions": 222,
                        "Daily Reviews": 333,
                    },
                )
            )
            snapshot = capture_snapshot_from_google_sheets("spreadsheet-123", client)
            self.assertEqual(101, snapshot["sheets"]["Experiments"]["sheet_id"])
            self.assertEqual("experiment_id", snapshot["sheets"]["Experiments"]["values"][0][0])
            self.assertTrue(validate_snapshot(snapshot)["valid"])

    def test_google_api_doctor_reports_contract_ready_with_fake_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            client = FakeSheetsApiClient(
                snapshot_from_tables(
                    load_workbook_tables(save_workbook(Path(tmpdir) / "template.xlsx")),
                    {sheet.name: index for index, sheet in enumerate(SHEETS, start=100)},
                )
            )
            with patch("lab_notebook_agent.google_api.GoogleSheetsApiClient.from_credentials", return_value=client):
                result = google_api_doctor("spreadsheet-123")
            self.assertTrue(result["ready"])
            self.assertEqual("passed", result["checks"][-1]["status"])

    def test_google_api_doctor_reports_credential_failure(self) -> None:
        with patch(
            "lab_notebook_agent.google_api.GoogleSheetsApiClient.from_credentials",
            side_effect=RuntimeError("credentials missing"),
        ):
            result = google_api_doctor("spreadsheet-123")
        self.assertFalse(result["ready"])
        self.assertEqual("failed", result["checks"][0]["status"])
        self.assertIn("credentials missing", result["checks"][0]["message"])

    def test_live_google_agent_run_applies_valid_batch_with_fake_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            works_path = write_fake_litscout_export(Path(tmpdir) / "works.json")
            client = FakeSheetsApiClient(
                snapshot_from_tables(
                    load_workbook_tables(workbook_path),
                    {
                        "Experiments": 101,
                        "Results": 102,
                        "Literature Evidence": 111,
                        "Agent Suggestions": 222,
                        "Daily Reviews": 333,
                    },
                )
            )
            run = run_live_google_agent(
                "spreadsheet-123",
                client,
                config=AgentRunConfig(experiment_ids=("EP-001",), litscout_export=str(works_path)),
                apply=True,
            )
            self.assertTrue(run["applied"])
            self.assertTrue(run["apply_audit"]["valid"], run["apply_audit"])
            self.assertEqual(2, len(run["batch_update_requests"]))
            self.assertEqual(1, len(client.batch_updates))
            self.assertEqual(222, run["batch_update_requests"][1]["appendCells"]["sheetId"])

    def test_live_google_daily_agent_run_applies_valid_batch_with_fake_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            works_path = write_fake_litscout_export(Path(tmpdir) / "works.json")
            client = FakeSheetsApiClient(
                snapshot_from_tables(
                    load_workbook_tables(workbook_path),
                    {
                        "Experiments": 101,
                        "Results": 102,
                        "Literature Evidence": 111,
                        "Agent Suggestions": 222,
                        "Daily Reviews": 333,
                    },
                )
            )
            run = run_live_google_daily_agent(
                "spreadsheet-123",
                client,
                config=AgentRunConfig(review_date="2026-06-09", litscout_export=str(works_path)),
                apply=True,
            )
            self.assertTrue(run["applied"])
            self.assertEqual("lab-notebook-agent-daily-run.v1", run["daily_agent_run"]["schema"])
            self.assertEqual(1, run["daily_summary"]["summary"]["experiment_count"])
            self.assertTrue(run["apply_audit"]["valid"], run["apply_audit"])
            self.assertEqual(7, len(run["batch_update_requests"]))
            self.assertEqual(102, run["batch_update_requests"][0]["appendCells"]["sheetId"])
            self.assertEqual(333, run["batch_update_requests"][3]["appendCells"]["sheetId"])
            self.assertEqual(101, run["batch_update_requests"][4]["updateCells"]["start"]["sheetId"])
            self.assertEqual(1, len(client.batch_updates))

    def test_live_google_formulation_normalization_applies_valid_batch_with_fake_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            workbook = load_workbook(workbook_path)
            workbook["Master Reagents"]["F2"] = "156.18"
            workbook["Master Reagents"]["G2"] = "1.05"
            workbook["Formulations"]["E2"] = "10"
            workbook.save(workbook_path)
            client = FakeSheetsApiClient(
                snapshot_from_tables(
                    load_workbook_tables(workbook_path),
                    {"Formulations": 103},
                )
            )
            run = run_live_google_formulation_normalization(
                "spreadsheet-123",
                client,
                experiment_ids=("EP-001",),
                apply=True,
            )
            self.assertTrue(run["applied"])
            self.assertEqual(
                "lab-notebook-agent-formulation-normalization.v1",
                run["formulation_normalization_report"]["schema"],
            )
            self.assertEqual(2, run["formulation_normalization_report"]["summary"]["formulation_cells_to_update"])
            self.assertTrue(run["apply_audit"]["valid"], run["apply_audit"])
            self.assertEqual(2, len(run["batch_update_requests"]))
            self.assertEqual(103, run["batch_update_requests"][0]["updateCells"]["start"]["sheetId"])
            self.assertEqual(5, run["batch_update_requests"][0]["updateCells"]["start"]["columnIndex"])
            self.assertEqual(6, run["batch_update_requests"][1]["updateCells"]["start"]["columnIndex"])
            self.assertEqual(1, len(client.batch_updates))

    def test_live_google_daily_log_results_normalization_applies_valid_batch_with_fake_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            client = FakeSheetsApiClient(
                snapshot_from_tables(
                    load_workbook_tables(workbook_path),
                    {"Results": 102},
                )
            )
            run = run_live_google_daily_log_results_normalization(
                "spreadsheet-123",
                client,
                experiment_ids=("EP-001",),
                review_date="2026-06-09",
                apply=True,
            )
            self.assertTrue(run["applied"])
            self.assertEqual("lab-notebook-agent-daily-log-results.v1", run["daily_log_results_report"]["schema"])
            self.assertEqual(2, run["daily_log_results_report"]["summary"]["result_rows_to_append"])
            self.assertTrue(run["apply_audit"]["valid"], run["apply_audit"])
            self.assertEqual(1, len(run["batch_update_requests"]))
            self.assertEqual(102, run["batch_update_requests"][0]["appendCells"]["sheetId"])
            self.assertEqual(2, len(run["batch_update_requests"][0]["appendCells"]["rows"]))
            self.assertEqual(1, len(client.batch_updates))

    def test_live_google_plan_materialization_applies_valid_batch_with_fake_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            works_path = write_fake_litscout_export(Path(tmpdir) / "works.json")
            accepted_path = Path(tmpdir) / "accepted.xlsx"
            run_workbook_agent(
                workbook_path,
                AgentRunConfig(experiment_ids=("EP-001",), litscout_export=str(works_path)),
                apply=True,
                output_workbook=accepted_path,
            )
            mark_first_suggestion_accepted(accepted_path)
            client = FakeSheetsApiClient(
                snapshot_from_tables(
                    load_workbook_tables(accepted_path),
                    {
                        "Experiments": 101,
                        "Formulations": 103,
                        "Results": 102,
                        "Literature Evidence": 111,
                        "Agent Suggestions": 222,
                    },
                )
            )
            run = run_live_google_plan_materialization(
                "spreadsheet-123",
                client,
                planned_date="2026-06-10",
                apply=True,
            )
            self.assertTrue(run["applied"])
            self.assertEqual(1, run["materialization_report"]["summary"]["experiment_rows_to_append"])
            self.assertEqual(3, run["materialization_report"]["summary"]["formulation_rows_to_append"])
            self.assertEqual(6, run["materialization_report"]["summary"]["result_rows_to_append"])
            self.assertEqual(101, run["batch_update_requests"][0]["appendCells"]["sheetId"])
            self.assertEqual(103, run["batch_update_requests"][1]["appendCells"]["sheetId"])
            self.assertEqual(102, run["batch_update_requests"][2]["appendCells"]["sheetId"])

    def test_accepted_suggestion_materializes_planned_experiment_and_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            works_path = write_fake_litscout_export(Path(tmpdir) / "works.json")
            suggested_path = Path(tmpdir) / "suggested.xlsx"
            run_workbook_agent(
                workbook_path,
                AgentRunConfig(experiment_ids=("EP-001",), litscout_export=str(works_path)),
                apply=True,
                output_workbook=suggested_path,
            )
            mark_first_suggestion_accepted(suggested_path)
            report = build_plan_materialization_report(
                load_workbook_tables(suggested_path),
                planned_date="2026-06-10",
            )
            self.assertEqual(1, report["summary"]["experiment_rows_to_append"])
            self.assertEqual(3, report["summary"]["formulation_rows_to_append"])
            self.assertEqual(6, report["summary"]["result_rows_to_append"])
            self.assertEqual("EP-001-FUP-001", report["runs"][0]["append_experiments"][0]["experiment_id"])

            planned_path = Path(tmpdir) / "planned.xlsx"
            apply_plan_materialization_report_to_workbook(suggested_path, report, planned_path)
            workbook = load_workbook(planned_path)
            self.assertEqual("EP-001-FUP-001", workbook["Experiments"]["A3"].value)
            self.assertEqual("2026-06-10", workbook["Experiments"]["B3"].value)
            self.assertEqual("EP-001-FUP-001", workbook["Formulations"]["A5"].value)
            self.assertEqual("M-SKA", workbook["Formulations"]["B5"].value)
            self.assertEqual("particle_size_nm", workbook["Results"]["C3"].value)
            self.assertEqual("run_planned", workbook["Agent Suggestions"]["M2"].value)

    def test_accepted_suggestion_materialization_emits_google_batch_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = save_workbook(Path(tmpdir) / "template.xlsx")
            works_path = write_fake_litscout_export(Path(tmpdir) / "works.json")
            suggested_path = Path(tmpdir) / "suggested.xlsx"
            run_workbook_agent(
                workbook_path,
                AgentRunConfig(experiment_ids=("EP-001",), litscout_export=str(works_path)),
                apply=True,
                output_workbook=suggested_path,
            )
            mark_first_suggestion_accepted(suggested_path)
            snapshot = snapshot_from_tables(
                load_workbook_tables(suggested_path),
                {
                    "Experiments": 101,
                    "Formulations": 103,
                    "Results": 102,
                    "Literature Evidence": 111,
                    "Agent Suggestions": 222,
                },
            )
            report = build_plan_materialization_report(
                snapshot_to_tables(snapshot),
                planned_date="2026-06-10",
            )
            audit = audit_report_against_snapshot(report, snapshot)
            self.assertTrue(audit["valid"], audit["errors"])
            self.assertEqual(3, audit["summary"]["formulation_rows_to_append"])
            requests = batch_update_requests_from_report(report, sheet_ids_from_snapshot(snapshot))
            self.assertEqual(4, len(requests))
            self.assertEqual(101, requests[0]["appendCells"]["sheetId"])
            self.assertEqual(103, requests[1]["appendCells"]["sheetId"])
            self.assertEqual(102, requests[2]["appendCells"]["sheetId"])
            self.assertEqual(222, requests[3]["updateCells"]["start"]["sheetId"])


def write_fake_litscout_export(path: Path) -> Path:
    path.write_text(
        json_dumps(
            [
                {
                    "title": "Role of anionic and nonionic surfactants on particle size",
                    "service": "openalex",
                    "author_names": ["A. Author", "B. Author"],
                    "year": 2006,
                    "doi": "10.1002/app.23717",
                    "url": "https://doi.org/10.1002/app.23717",
                    "cited_by_count": 10,
                    "concepts": [
                        {"display_name": "Emulsion polymerization"},
                        {"display_name": "Particle size"},
                        {"display_name": "Surfactant"},
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


def mark_first_suggestion_accepted(path: Path) -> None:
    workbook = load_workbook(path)
    worksheet = workbook["Agent Suggestions"]
    headers = [cell.value for cell in worksheet[1]]
    status_column = headers.index("status") + 1
    worksheet.cell(row=2, column=status_column, value="accepted")
    workbook.save(path)


class FakeSheetsApiClient:
    def __init__(self, snapshot: dict[str, object]) -> None:
        self.snapshot = snapshot
        self.batch_updates: list[list[dict[str, object]]] = []

    def get_metadata(self, spreadsheet_id: str) -> dict[str, object]:
        sheets = []
        for sheet_name, payload in self.snapshot["sheets"].items():
            sheets.append(
                {
                    "properties": {
                        "title": sheet_name,
                        "sheetId": payload.get("sheet_id"),
                    }
                }
            )
        return {
            "spreadsheetId": spreadsheet_id,
            "sheets": sheets,
        }

    def get_values(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        value_range: str,
        value_render_option: str = "FORMATTED_VALUE",
    ) -> list[list[object]]:
        return self.snapshot["sheets"][sheet_name]["values"]

    def batch_update(self, spreadsheet_id: str, requests: list[dict[str, object]]) -> dict[str, object]:
        self.batch_updates.append(requests)
        return {
            "spreadsheetId": spreadsheet_id,
            "replies": [{} for _ in requests],
        }


def json_dumps(value: object) -> str:
    import json

    return json.dumps(value, indent=2) + "\n"


if __name__ == "__main__":
    unittest.main()
