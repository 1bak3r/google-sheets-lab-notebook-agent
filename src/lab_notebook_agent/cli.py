from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .agent import AgentRunConfig, build_agent_report, run_workbook_agent
from .daily_agent import build_snapshot_daily_agent_run, run_workbook_daily_agent
from .daily_log_results import apply_daily_log_results_report_to_workbook, build_daily_log_results_report
from .daily_summary import build_daily_summary_report
from .experiment_record import (
    apply_experiment_record_report_to_workbook,
    build_experiment_record_report,
    load_experiment_record,
)
from .formulation_normalization import (
    apply_formulation_normalization_report_to_workbook,
    build_formulation_normalization_report,
)
from .google_sheets import (
    audit_report_against_snapshot,
    batch_update_requests_from_report,
    load_agent_report,
    load_sheet_snapshot,
    sheet_ids_from_snapshot,
    snapshot_capture_plan,
    snapshot_to_tables,
    validate_snapshot,
)
from .google_api import (
    GoogleCredentialsConfig,
    GoogleSheetsApiClient,
    capture_snapshot_from_google_sheets,
    google_api_doctor,
    run_live_google_daily_agent,
    run_live_google_daily_log_results_normalization,
    run_live_google_agent,
    run_live_google_experiment_record,
    run_live_google_formulation_normalization,
    run_live_google_plan_materialization,
    run_live_google_recorded_daily_agent,
    run_live_google_setup,
)
from .litscout import evidence_rows_to_values, litscout_works_to_evidence_rows, load_litscout_export
from .material_scaffold import apply_material_scaffold_report_to_workbook, build_material_scaffold_report
from .material_search import build_process_material_search_report
from .materials import audit_experiment_materials
from .notebook_search import search_notebook_tables
from .planning import apply_plan_materialization_report_to_workbook, build_plan_materialization_report
from .preflight import build_experiment_preflight_report
from .recommend import build_recommendation, load_entry
from .recorded_daily_agent import build_snapshot_recorded_daily_agent_run, run_workbook_recorded_daily_agent
from .schema import workbook_contract
from .search import LocalSemanticIndex, load_knowledge
from .sheets import append_suggestion_to_workbook, save_entry_from_workbook, suggest_from_workbook
from .sheets import load_workbook_tables
from .templates import save_workbook


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lab-notebook-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Generate the Sheets-ready lab notebook workbook.")
    init_parser.add_argument("--output", default="artifacts/lab_notebook_template.xlsx")
    init_parser.add_argument("--no-examples", action="store_true", help="Do not include seed/example rows.")

    search_parser = subparsers.add_parser("search-knowledge", help="Search local process knowledge.")
    search_parser.add_argument("query")
    search_parser.add_argument("--knowledge", help="Optional process knowledge JSON file.")
    search_parser.add_argument("-k", type=int, default=5)

    search_notebook_parser = subparsers.add_parser("search-notebook", help="Search notebook rows across workbook or snapshot tabs.")
    search_notebook_source = search_notebook_parser.add_mutually_exclusive_group(required=True)
    search_notebook_source.add_argument("--workbook", help="Lab notebook .xlsx file.")
    search_notebook_source.add_argument("--snapshot", help="Google Sheets snapshot JSON file.")
    search_notebook_parser.add_argument("query")
    search_notebook_parser.add_argument("--sheet", action="append", default=[], help="Restrict search to a sheet. Repeatable.")
    search_notebook_parser.add_argument("-k", type=int, default=10)
    search_notebook_parser.add_argument("--output", help="Optional output JSON path. Defaults to stdout.")

    search_materials_parser = subparsers.add_parser("search-materials", help="Find process-role-aware Master Reagents candidates.")
    search_materials_source = search_materials_parser.add_mutually_exclusive_group(required=True)
    search_materials_source.add_argument("--workbook", help="Lab notebook .xlsx file.")
    search_materials_source.add_argument("--snapshot", help="Google Sheets snapshot JSON file.")
    search_materials_parser.add_argument("--experiment-id", help="Experiment ID to derive process type and current formulation rows.")
    search_materials_parser.add_argument("--process-type", help="Process type to search, such as emulsion polymerization.")
    search_materials_parser.add_argument("--query", default="", help="Optional extra search terms.")
    search_materials_parser.add_argument("--include-optional", action="store_true", help="Include optional roles such as crosslinker or chain-transfer agent.")
    search_materials_parser.add_argument("-k", type=int, default=3, help="Candidate rows to return per role.")
    search_materials_parser.add_argument("--output", help="Optional output JSON path. Defaults to stdout.")

    daily_summary_parser = subparsers.add_parser("daily-summary", help="Summarize experiments, observations, results, audits, and open suggestions for a review date.")
    daily_summary_source = daily_summary_parser.add_mutually_exclusive_group(required=True)
    daily_summary_source.add_argument("--workbook", help="Lab notebook .xlsx file.")
    daily_summary_source.add_argument("--snapshot", help="Google Sheets snapshot JSON file.")
    daily_summary_parser.add_argument("--review-date", required=True, help="Review date as YYYY-MM-DD.")
    daily_summary_parser.add_argument("--experiment-id", action="append", default=[], help="Experiment ID to include. Repeatable. Defaults to date-selected experiments.")
    daily_summary_parser.add_argument("--output", help="Optional output JSON path. Defaults to stdout.")

    preflight_parser = subparsers.add_parser("experiment-preflight", help="Check whether one experiment is ready for planning, running, or result-driven review.")
    preflight_source = preflight_parser.add_mutually_exclusive_group(required=True)
    preflight_source.add_argument("--workbook", help="Lab notebook .xlsx file.")
    preflight_source.add_argument("--snapshot", help="Google Sheets snapshot JSON file.")
    preflight_parser.add_argument("--experiment-id", required=True)
    preflight_parser.add_argument("--stage", choices=("planning", "review"), default="planning")
    preflight_parser.add_argument("--output", help="Optional output JSON path. Defaults to stdout.")

    record_parser = subparsers.add_parser(
        "record-experiment",
        help="Convert a structured experiment record JSON into notebook rows and optional Google batch requests.",
    )
    record_parser.add_argument("--record", required=True, help="Experiment record JSON file.")
    record_parser.add_argument("--workbook", help="Lab notebook .xlsx file for apply mode.")
    record_parser.add_argument("--snapshot", help="Google Sheets snapshot JSON file for audit and batch mode.")
    record_parser.add_argument("--apply", action="store_true", help="Append generated rows to the workbook.")
    record_parser.add_argument("--workbook-output", help="Optional output .xlsx path for workbook apply mode. Defaults to in-place.")
    record_parser.add_argument("--report-output", help="Optional record report JSON path. Defaults to stdout.")
    record_parser.add_argument("--audit-output", help="Optional snapshot audit JSON path.")
    record_parser.add_argument("--batch-output", help="Optional Google Sheets batchUpdate request JSON path for snapshot mode.")

    record_daily_parser = subparsers.add_parser(
        "record-daily-agent-run",
        help="Project a structured experiment record into the notebook and run the daily agent against that projected state.",
    )
    record_daily_source = record_daily_parser.add_mutually_exclusive_group(required=True)
    record_daily_source.add_argument("--workbook", help="Lab notebook .xlsx file.")
    record_daily_source.add_argument("--snapshot", help="Google Sheets snapshot JSON file.")
    record_daily_parser.add_argument("--record", required=True, help="Experiment record JSON file.")
    record_daily_parser.add_argument("--review-date", help="Review date as YYYY-MM-DD. Defaults to the record experiment date.")
    record_daily_parser.add_argument("--experiment-id", action="append", default=[], help="Experiment ID to process. Repeatable. Defaults to the record experiment.")
    record_daily_parser.add_argument("--context-limit", type=int, default=5, help="Notebook search matches to include per run. Use 0 to disable.")
    record_daily_parser.add_argument("--history-limit", type=int, default=5, help="Same-process prior experiments to include per run. Use 0 to disable.")
    record_daily_parser.add_argument("--litscout-export", help="Optional LitScout JSON array export to convert into evidence rows.")
    record_daily_parser.add_argument("--run-litscout", action="store_true", help="Run LitScout live for experiments that lack evidence.")
    record_daily_parser.add_argument("--litscout-sources", default="openalex,crossref,semantic_scholar")
    record_daily_parser.add_argument("--litscout-depth", default="light")
    record_daily_parser.add_argument("--litscout-limit", type=int, default=8)
    record_daily_parser.add_argument("--evidence-limit", type=int, default=3)
    record_daily_parser.add_argument("--artifacts-dir", default="artifacts")
    record_daily_parser.add_argument("--force", action="store_true", help="Generate a new suggestion even if one already exists.")
    record_daily_parser.add_argument("--apply", action="store_true", help="Append generated rows and updates to the workbook.")
    record_daily_parser.add_argument("--workbook-output", help="Optional output .xlsx path for workbook apply mode. Defaults to in-place.")
    record_daily_parser.add_argument("--run-output", help="Optional full recorded daily run JSON path. Defaults to stdout.")
    record_daily_parser.add_argument("--record-output", help="Optional experiment record report JSON path.")
    record_daily_parser.add_argument("--daily-run-output", help="Optional projected daily agent run JSON path.")
    record_daily_parser.add_argument("--audit-output", help="Optional snapshot apply audit JSON path. Snapshot source only.")
    record_daily_parser.add_argument("--batch-output", help="Optional Google Sheets batchUpdate request JSON path. Snapshot source only.")

    normalize_log_parser = subparsers.add_parser(
        "normalize-daily-log-results",
        help="Convert structured Daily Log measurement fields into appendable Results rows.",
    )
    normalize_log_source = normalize_log_parser.add_mutually_exclusive_group(required=True)
    normalize_log_source.add_argument("--workbook", help="Lab notebook .xlsx file.")
    normalize_log_source.add_argument("--snapshot", help="Google Sheets snapshot JSON file.")
    normalize_log_parser.add_argument("--experiment-id", action="append", default=[], help="Experiment ID to include. Repeatable.")
    normalize_log_parser.add_argument("--review-date", help="Only normalize Daily Log timestamps starting with YYYY-MM-DD.")
    normalize_log_parser.add_argument("--apply", action="store_true", help="Append generated Results rows to the workbook.")
    normalize_log_parser.add_argument("--workbook-output", help="Optional output .xlsx path for workbook apply mode. Defaults to in-place.")
    normalize_log_parser.add_argument("--report-output", help="Optional normalization report JSON path. Defaults to stdout.")
    normalize_log_parser.add_argument("--batch-output", help="Optional Google Sheets batchUpdate request JSON path for snapshot mode.")

    normalize_formulations_parser = subparsers.add_parser(
        "normalize-formulations",
        help="Derive missing Formulations mass, volume, or moles from existing quantities and Master Reagents properties.",
    )
    normalize_formulations_source = normalize_formulations_parser.add_mutually_exclusive_group(required=True)
    normalize_formulations_source.add_argument("--workbook", help="Lab notebook .xlsx file.")
    normalize_formulations_source.add_argument("--snapshot", help="Google Sheets snapshot JSON file.")
    normalize_formulations_parser.add_argument("--experiment-id", action="append", default=[], help="Experiment ID to include. Repeatable.")
    normalize_formulations_parser.add_argument("--apply", action="store_true", help="Update generated Formulations cells in the workbook.")
    normalize_formulations_parser.add_argument("--workbook-output", help="Optional output .xlsx path for workbook apply mode. Defaults to in-place.")
    normalize_formulations_parser.add_argument("--report-output", help="Optional normalization report JSON path. Defaults to stdout.")
    normalize_formulations_parser.add_argument("--batch-output", help="Optional Google Sheets batchUpdate request JSON path for snapshot mode.")

    daily_agent_parser = subparsers.add_parser("daily-agent-run", help="Run a daily summary plus suggestion agent in one report.")
    daily_agent_source = daily_agent_parser.add_mutually_exclusive_group(required=True)
    daily_agent_source.add_argument("--workbook", help="Lab notebook .xlsx file.")
    daily_agent_source.add_argument("--snapshot", help="Google Sheets snapshot JSON file.")
    daily_agent_parser.add_argument("--review-date", required=True, help="Review date as YYYY-MM-DD.")
    daily_agent_parser.add_argument("--experiment-id", action="append", default=[], help="Experiment ID to process. Repeatable. Defaults to date-selected experiments.")
    daily_agent_parser.add_argument("--context-limit", type=int, default=5, help="Notebook search matches to include per run. Use 0 to disable.")
    daily_agent_parser.add_argument("--history-limit", type=int, default=5, help="Same-process prior experiments to include per run. Use 0 to disable.")
    daily_agent_parser.add_argument("--litscout-export", help="Optional LitScout JSON array export to convert into evidence rows.")
    daily_agent_parser.add_argument("--run-litscout", action="store_true", help="Run LitScout live for each experiment that lacks evidence.")
    daily_agent_parser.add_argument("--litscout-sources", default="openalex,crossref,semantic_scholar")
    daily_agent_parser.add_argument("--litscout-depth", default="light")
    daily_agent_parser.add_argument("--litscout-limit", type=int, default=8)
    daily_agent_parser.add_argument("--evidence-limit", type=int, default=3)
    daily_agent_parser.add_argument("--artifacts-dir", default="artifacts")
    daily_agent_parser.add_argument("--force", action="store_true", help="Generate a new suggestion even if one already exists.")
    daily_agent_parser.add_argument("--apply", action="store_true", help="Append agent rows to the workbook. Workbook source only.")
    daily_agent_parser.add_argument("--workbook-output", help="Optional output .xlsx path for apply mode. Defaults to in-place.")
    daily_agent_parser.add_argument("--run-output", help="Optional full daily run JSON path. Defaults to stdout.")
    daily_agent_parser.add_argument("--summary-output", help="Optional daily summary JSON path.")
    daily_agent_parser.add_argument("--report-output", help="Optional agent report JSON path.")
    daily_agent_parser.add_argument("--audit-output", help="Optional snapshot apply audit JSON path. Snapshot source only.")
    daily_agent_parser.add_argument("--batch-output", help="Optional Google Sheets batchUpdate request JSON path. Snapshot source only.")

    schema_parser = subparsers.add_parser("schema", help="Emit the workbook contract as JSON.")
    schema_parser.add_argument("--output", help="Optional output JSON path. Defaults to stdout.")

    suggest_parser = subparsers.add_parser("suggest", help="Draft a next-experiment suggestion from a JSON entry.")
    suggest_parser.add_argument("--entry", required=True, help="Experiment entry JSON file.")
    suggest_parser.add_argument("--knowledge", help="Optional process knowledge JSON file.")
    suggest_parser.add_argument("--output", help="Optional output JSON path. Defaults to stdout.")

    audit_entry_parser = subparsers.add_parser("audit-entry", help="Audit material roles and quantitative fields in an experiment JSON entry.")
    audit_entry_parser.add_argument("--entry", required=True)
    audit_entry_parser.add_argument("--output", help="Optional output JSON path. Defaults to stdout.")

    entry_parser = subparsers.add_parser("entry-from-workbook", help="Assemble one experiment entry from workbook tabs.")
    entry_parser.add_argument("--workbook", required=True, help="Lab notebook .xlsx file.")
    entry_parser.add_argument("--experiment-id", required=True)
    entry_parser.add_argument("--output", required=True)

    suggest_workbook_parser = subparsers.add_parser("suggest-workbook", help="Draft a suggestion from workbook tabs.")
    suggest_workbook_parser.add_argument("--workbook", required=True, help="Lab notebook .xlsx file.")
    suggest_workbook_parser.add_argument("--experiment-id", required=True)
    suggest_workbook_parser.add_argument("--knowledge", help="Optional process knowledge JSON file.")
    suggest_workbook_parser.add_argument("--output", help="Optional output JSON path. Defaults to stdout.")
    suggest_workbook_parser.add_argument(
        "--append-to-workbook",
        help="Optional .xlsx output path. Appends the suggestion to Agent Suggestions.",
    )

    audit_workbook_parser = subparsers.add_parser("audit-workbook", help="Audit material roles and quantitative fields for one workbook experiment.")
    audit_workbook_parser.add_argument("--workbook", required=True)
    audit_workbook_parser.add_argument("--experiment-id", required=True)
    audit_workbook_parser.add_argument("--output", help="Optional output JSON path. Defaults to stdout.")

    evidence_parser = subparsers.add_parser("evidence-from-litscout", help="Convert a LitScout JSON export to Literature Evidence rows.")
    evidence_parser.add_argument("--input", required=True, help="LitScout JSON array export.")
    evidence_parser.add_argument("--experiment-id", required=True)
    evidence_parser.add_argument("--query", required=True)
    evidence_parser.add_argument("--limit", type=int, default=5)
    evidence_parser.add_argument("--values", action="store_true", help="Emit Sheets-ready values instead of row dictionaries.")
    evidence_parser.add_argument("--output", help="Optional output JSON path. Defaults to stdout.")

    agent_parser = subparsers.add_parser("agent-run", help="Run the workbook-backed lab notebook agent.")
    agent_parser.add_argument("--workbook", required=True, help="Lab notebook .xlsx file.")
    agent_parser.add_argument("--experiment-id", action="append", default=[], help="Experiment ID to process. Repeatable. Defaults to all non-abandoned experiments.")
    agent_parser.add_argument("--review-date", help="Only process experiments dated/logged on YYYY-MM-DD unless experiment IDs are provided.")
    agent_parser.add_argument("--context-limit", type=int, default=5, help="Notebook search matches to include per run. Use 0 to disable.")
    agent_parser.add_argument("--history-limit", type=int, default=5, help="Same-process prior experiments to include per run. Use 0 to disable.")
    agent_parser.add_argument("--litscout-export", help="Optional LitScout JSON array export to convert into evidence rows.")
    agent_parser.add_argument("--run-litscout", action="store_true", help="Run LitScout live for each experiment that lacks evidence.")
    agent_parser.add_argument("--litscout-sources", default="openalex,crossref,semantic_scholar")
    agent_parser.add_argument("--litscout-depth", default="light")
    agent_parser.add_argument("--litscout-limit", type=int, default=8)
    agent_parser.add_argument("--evidence-limit", type=int, default=3)
    agent_parser.add_argument("--artifacts-dir", default="artifacts")
    agent_parser.add_argument("--force", action="store_true", help="Generate a new suggestion even if one already exists.")
    agent_parser.add_argument("--apply", action="store_true", help="Append report rows to the workbook.")
    agent_parser.add_argument("--workbook-output", help="Optional output .xlsx path for apply mode. Defaults to in-place.")
    agent_parser.add_argument("--report-output", help="Optional report JSON path. Defaults to stdout.")

    batch_parser = subparsers.add_parser("google-batch-from-report", help="Emit Google Sheets batchUpdate requests from an agent report.")
    batch_parser.add_argument("--report", required=True, help="Agent report JSON file.")
    batch_parser.add_argument("--master-reagents-sheet-id", type=int)
    batch_parser.add_argument("--experiments-sheet-id", type=int)
    batch_parser.add_argument("--formulations-sheet-id", type=int)
    batch_parser.add_argument("--results-sheet-id", type=int)
    batch_parser.add_argument("--literature-evidence-sheet-id", type=int)
    batch_parser.add_argument("--agent-suggestions-sheet-id", type=int)
    batch_parser.add_argument("--daily-reviews-sheet-id", type=int)
    batch_parser.add_argument("--output", help="Optional output JSON path. Defaults to stdout.")

    snapshot_parser = subparsers.add_parser("agent-run-snapshot", help="Run the lab notebook agent from a Google Sheets range snapshot JSON.")
    snapshot_parser.add_argument("--snapshot", required=True, help="Snapshot JSON file with tab values.")
    snapshot_parser.add_argument("--experiment-id", action="append", default=[], help="Experiment ID to process. Repeatable.")
    snapshot_parser.add_argument("--review-date", help="Only process experiments dated/logged on YYYY-MM-DD unless experiment IDs are provided.")
    snapshot_parser.add_argument("--context-limit", type=int, default=5, help="Notebook search matches to include per run. Use 0 to disable.")
    snapshot_parser.add_argument("--history-limit", type=int, default=5, help="Same-process prior experiments to include per run. Use 0 to disable.")
    snapshot_parser.add_argument("--litscout-export", help="Optional LitScout JSON array export to convert into evidence rows.")
    snapshot_parser.add_argument("--run-litscout", action="store_true", help="Run LitScout live for each experiment that lacks evidence.")
    snapshot_parser.add_argument("--litscout-sources", default="openalex,crossref,semantic_scholar")
    snapshot_parser.add_argument("--litscout-depth", default="light")
    snapshot_parser.add_argument("--litscout-limit", type=int, default=8)
    snapshot_parser.add_argument("--evidence-limit", type=int, default=3)
    snapshot_parser.add_argument("--artifacts-dir", default="artifacts")
    snapshot_parser.add_argument("--force", action="store_true", help="Generate a new suggestion even if one already exists.")
    snapshot_parser.add_argument("--report-output", help="Optional report JSON path. Defaults to stdout.")
    snapshot_parser.add_argument("--batch-output", help="Optional Google Sheets batchUpdate request JSON path.")

    workbook_snapshot_parser = subparsers.add_parser("snapshot-from-workbook", help="Emit a Google Sheets-style snapshot from a workbook.")
    workbook_snapshot_parser.add_argument("--workbook", required=True)
    workbook_snapshot_parser.add_argument(
        "--sheet-id",
        action="append",
        default=[],
        help="Optional sheet ID mapping as 'Sheet Name=123'. Repeatable.",
    )
    workbook_snapshot_parser.add_argument("--output", help="Optional snapshot JSON path. Defaults to stdout.")

    validate_snapshot_parser = subparsers.add_parser("validate-snapshot", help="Validate a Google Sheets snapshot and optional agent report before apply.")
    validate_snapshot_parser.add_argument("--snapshot", required=True)
    validate_snapshot_parser.add_argument("--report", help="Optional agent report to audit against the snapshot.")
    validate_snapshot_parser.add_argument("--require-sheet-ids", action="store_true")
    validate_snapshot_parser.add_argument("--output", help="Optional audit JSON path. Defaults to stdout.")

    capture_plan_parser = subparsers.add_parser("google-capture-plan", help="Emit the Google Sheets ranges needed to build a snapshot.")
    capture_plan_parser.add_argument("--spreadsheet-id", default="")
    capture_plan_parser.add_argument("--range", default="A1:Z1000")
    capture_plan_parser.add_argument("--output", help="Optional capture plan JSON path. Defaults to stdout.")

    google_snapshot_parser = subparsers.add_parser("google-snapshot", help="Capture a live Google Sheet snapshot using Google API credentials.")
    google_snapshot_parser.add_argument("--spreadsheet-id", required=True)
    google_snapshot_parser.add_argument("--service-account-file", help="Optional service account JSON file. Defaults to Application Default Credentials.")
    google_snapshot_parser.add_argument("--range", default="A1:Z1000")
    google_snapshot_parser.add_argument("--output", required=True)

    google_doctor_parser = subparsers.add_parser("google-doctor", help="Check direct Google Sheets API dependencies, credentials, and optional spreadsheet access.")
    google_doctor_parser.add_argument("--spreadsheet-id", help="Optional spreadsheet ID to verify metadata/contract access.")
    google_doctor_parser.add_argument("--service-account-file", help="Optional service account JSON file. Defaults to Application Default Credentials.")
    google_doctor_parser.add_argument("--output", help="Optional output JSON path. Defaults to stdout.")

    google_setup_parser = subparsers.add_parser(
        "google-setup-live",
        help="Create or repair live Google Sheet tabs, headers, frozen rows, and dropdowns from the workbook contract.",
    )
    google_setup_parser.add_argument("--spreadsheet-id", required=True)
    google_setup_parser.add_argument("--service-account-file", help="Optional service account JSON file. Defaults to Application Default Credentials.")
    google_setup_parser.add_argument("--no-validations", action="store_true", help="Do not add controlled-vocabulary dropdown validation rules.")
    google_setup_parser.add_argument("--validation-end-row", type=int, default=1000, help="Apply dropdown validations through this 1-based row number.")
    google_setup_parser.add_argument("--apply", action="store_true", help="Apply the setup batchUpdate requests to the live spreadsheet.")
    google_setup_parser.add_argument("--run-output", help="Optional full live setup run JSON path. Defaults to stdout.")
    google_setup_parser.add_argument("--metadata-output", help="Optional spreadsheet metadata JSON path.")
    google_setup_parser.add_argument("--audit-output", help="Optional setup audit JSON path.")
    google_setup_parser.add_argument("--batch-output", help="Optional setup batchUpdate requests JSON path.")

    google_agent_parser = subparsers.add_parser("google-agent-run-live", help="Capture, run, audit, and optionally apply the lab notebook agent against a live Google Sheet.")
    google_agent_parser.add_argument("--spreadsheet-id", required=True)
    google_agent_parser.add_argument("--service-account-file", help="Optional service account JSON file. Defaults to Application Default Credentials.")
    google_agent_parser.add_argument("--range", default="A1:Z1000")
    google_agent_parser.add_argument("--experiment-id", action="append", default=[], help="Experiment ID to process. Repeatable.")
    google_agent_parser.add_argument("--review-date", help="Only process experiments dated/logged on YYYY-MM-DD unless experiment IDs are provided.")
    google_agent_parser.add_argument("--context-limit", type=int, default=5, help="Notebook search matches to include per run. Use 0 to disable.")
    google_agent_parser.add_argument("--history-limit", type=int, default=5, help="Same-process prior experiments to include per run. Use 0 to disable.")
    google_agent_parser.add_argument("--litscout-export", help="Optional LitScout JSON array export to convert into evidence rows.")
    google_agent_parser.add_argument("--run-litscout", action="store_true", help="Run LitScout live for experiments that lack evidence.")
    google_agent_parser.add_argument("--litscout-sources", default="openalex,crossref,semantic_scholar")
    google_agent_parser.add_argument("--litscout-depth", default="light")
    google_agent_parser.add_argument("--litscout-limit", type=int, default=8)
    google_agent_parser.add_argument("--evidence-limit", type=int, default=3)
    google_agent_parser.add_argument("--artifacts-dir", default="artifacts")
    google_agent_parser.add_argument("--force", action="store_true", help="Generate a new suggestion even if one already exists.")
    google_agent_parser.add_argument("--apply", action="store_true", help="Apply valid batchUpdate requests to the live spreadsheet.")
    google_agent_parser.add_argument("--run-output", help="Optional full live run JSON path. Defaults to stdout.")
    google_agent_parser.add_argument("--snapshot-output", help="Optional captured snapshot JSON path.")
    google_agent_parser.add_argument("--report-output", help="Optional agent report JSON path.")
    google_agent_parser.add_argument("--audit-output", help="Optional apply audit JSON path.")
    google_agent_parser.add_argument("--batch-output", help="Optional batchUpdate requests JSON path.")

    google_record_parser = subparsers.add_parser(
        "google-record-experiment-live",
        help="Capture a live Google Sheet, audit a structured experiment record, and optionally apply generated rows.",
    )
    google_record_parser.add_argument("--spreadsheet-id", required=True)
    google_record_parser.add_argument("--service-account-file", help="Optional service account JSON file. Defaults to Application Default Credentials.")
    google_record_parser.add_argument("--range", default="A1:Z1000")
    google_record_parser.add_argument("--record", required=True, help="Experiment record JSON file.")
    google_record_parser.add_argument("--apply", action="store_true", help="Apply valid batchUpdate requests to the live spreadsheet.")
    google_record_parser.add_argument("--run-output", help="Optional full live record run JSON path. Defaults to stdout.")
    google_record_parser.add_argument("--snapshot-output", help="Optional captured snapshot JSON path.")
    google_record_parser.add_argument("--report-output", help="Optional record report JSON path.")
    google_record_parser.add_argument("--audit-output", help="Optional apply audit JSON path.")
    google_record_parser.add_argument("--batch-output", help="Optional batchUpdate requests JSON path.")

    google_record_daily_parser = subparsers.add_parser(
        "google-record-daily-agent-run-live",
        help="Capture a live Google Sheet, project a structured record, run the daily agent, audit, and optionally apply.",
    )
    google_record_daily_parser.add_argument("--spreadsheet-id", required=True)
    google_record_daily_parser.add_argument("--service-account-file", help="Optional service account JSON file. Defaults to Application Default Credentials.")
    google_record_daily_parser.add_argument("--range", default="A1:Z1000")
    google_record_daily_parser.add_argument("--record", required=True, help="Experiment record JSON file.")
    google_record_daily_parser.add_argument("--review-date", help="Review date as YYYY-MM-DD. Defaults to the record experiment date.")
    google_record_daily_parser.add_argument("--experiment-id", action="append", default=[], help="Experiment ID to process. Repeatable. Defaults to the record experiment.")
    google_record_daily_parser.add_argument("--context-limit", type=int, default=5, help="Notebook search matches to include per run. Use 0 to disable.")
    google_record_daily_parser.add_argument("--history-limit", type=int, default=5, help="Same-process prior experiments to include per run. Use 0 to disable.")
    google_record_daily_parser.add_argument("--litscout-export", help="Optional LitScout JSON array export to convert into evidence rows.")
    google_record_daily_parser.add_argument("--run-litscout", action="store_true", help="Run LitScout live for experiments that lack evidence.")
    google_record_daily_parser.add_argument("--litscout-sources", default="openalex,crossref,semantic_scholar")
    google_record_daily_parser.add_argument("--litscout-depth", default="light")
    google_record_daily_parser.add_argument("--litscout-limit", type=int, default=8)
    google_record_daily_parser.add_argument("--evidence-limit", type=int, default=3)
    google_record_daily_parser.add_argument("--artifacts-dir", default="artifacts")
    google_record_daily_parser.add_argument("--force", action="store_true", help="Generate a new suggestion even if one already exists.")
    google_record_daily_parser.add_argument("--apply", action="store_true", help="Apply valid batchUpdate requests to the live spreadsheet.")
    google_record_daily_parser.add_argument("--run-output", help="Optional full live recorded daily run JSON path. Defaults to stdout.")
    google_record_daily_parser.add_argument("--snapshot-output", help="Optional captured snapshot JSON path.")
    google_record_daily_parser.add_argument("--record-output", help="Optional experiment record report JSON path.")
    google_record_daily_parser.add_argument("--daily-run-output", help="Optional projected daily agent run JSON path.")
    google_record_daily_parser.add_argument("--audit-output", help="Optional apply audit JSON path.")
    google_record_daily_parser.add_argument("--batch-output", help="Optional batchUpdate requests JSON path.")

    google_daily_agent_parser = subparsers.add_parser(
        "google-daily-agent-run-live",
        help="Capture, run a daily notebook review, audit, and optionally apply against a live Google Sheet.",
    )
    google_daily_agent_parser.add_argument("--spreadsheet-id", required=True)
    google_daily_agent_parser.add_argument("--service-account-file", help="Optional service account JSON file. Defaults to Application Default Credentials.")
    google_daily_agent_parser.add_argument("--range", default="A1:Z1000")
    google_daily_agent_parser.add_argument("--review-date", required=True, help="Review date as YYYY-MM-DD.")
    google_daily_agent_parser.add_argument("--experiment-id", action="append", default=[], help="Experiment ID to process. Repeatable.")
    google_daily_agent_parser.add_argument("--context-limit", type=int, default=5, help="Notebook search matches to include per run. Use 0 to disable.")
    google_daily_agent_parser.add_argument("--history-limit", type=int, default=5, help="Same-process prior experiments to include per run. Use 0 to disable.")
    google_daily_agent_parser.add_argument("--litscout-export", help="Optional LitScout JSON array export to convert into evidence rows.")
    google_daily_agent_parser.add_argument("--run-litscout", action="store_true", help="Run LitScout live for experiments that lack evidence.")
    google_daily_agent_parser.add_argument("--litscout-sources", default="openalex,crossref,semantic_scholar")
    google_daily_agent_parser.add_argument("--litscout-depth", default="light")
    google_daily_agent_parser.add_argument("--litscout-limit", type=int, default=8)
    google_daily_agent_parser.add_argument("--evidence-limit", type=int, default=3)
    google_daily_agent_parser.add_argument("--artifacts-dir", default="artifacts")
    google_daily_agent_parser.add_argument("--force", action="store_true", help="Generate a new suggestion even if one already exists.")
    google_daily_agent_parser.add_argument("--apply", action="store_true", help="Apply valid batchUpdate requests to the live spreadsheet.")
    google_daily_agent_parser.add_argument("--run-output", help="Optional full live daily run JSON path. Defaults to stdout.")
    google_daily_agent_parser.add_argument("--snapshot-output", help="Optional captured snapshot JSON path.")
    google_daily_agent_parser.add_argument("--daily-run-output", help="Optional combined daily run JSON path.")
    google_daily_agent_parser.add_argument("--summary-output", help="Optional daily summary JSON path.")
    google_daily_agent_parser.add_argument("--report-output", help="Optional agent report JSON path.")
    google_daily_agent_parser.add_argument("--audit-output", help="Optional apply audit JSON path.")
    google_daily_agent_parser.add_argument("--batch-output", help="Optional batchUpdate requests JSON path.")

    google_normalize_formulations_parser = subparsers.add_parser(
        "google-normalize-formulations-live",
        help="Capture a live Google Sheet, normalize formulation quantity cells, audit, and optionally apply.",
    )
    google_normalize_formulations_parser.add_argument("--spreadsheet-id", required=True)
    google_normalize_formulations_parser.add_argument("--service-account-file", help="Optional service account JSON file. Defaults to Application Default Credentials.")
    google_normalize_formulations_parser.add_argument("--range", default="A1:Z1000")
    google_normalize_formulations_parser.add_argument("--experiment-id", action="append", default=[], help="Experiment ID to include. Repeatable.")
    google_normalize_formulations_parser.add_argument("--apply", action="store_true", help="Apply valid batchUpdate requests to the live spreadsheet.")
    google_normalize_formulations_parser.add_argument("--run-output", help="Optional full live normalization run JSON path. Defaults to stdout.")
    google_normalize_formulations_parser.add_argument("--snapshot-output", help="Optional captured snapshot JSON path.")
    google_normalize_formulations_parser.add_argument("--report-output", help="Optional formulation normalization report JSON path.")
    google_normalize_formulations_parser.add_argument("--audit-output", help="Optional apply audit JSON path.")
    google_normalize_formulations_parser.add_argument("--batch-output", help="Optional batchUpdate requests JSON path.")

    google_normalize_daily_log_parser = subparsers.add_parser(
        "google-normalize-daily-log-results-live",
        help="Capture a live Google Sheet, normalize Daily Log measurements to Results, audit, and optionally apply.",
    )
    google_normalize_daily_log_parser.add_argument("--spreadsheet-id", required=True)
    google_normalize_daily_log_parser.add_argument("--service-account-file", help="Optional service account JSON file. Defaults to Application Default Credentials.")
    google_normalize_daily_log_parser.add_argument("--range", default="A1:Z1000")
    google_normalize_daily_log_parser.add_argument("--experiment-id", action="append", default=[], help="Experiment ID to include. Repeatable.")
    google_normalize_daily_log_parser.add_argument("--review-date", help="Only normalize Daily Log timestamps starting with YYYY-MM-DD.")
    google_normalize_daily_log_parser.add_argument("--apply", action="store_true", help="Apply valid batchUpdate requests to the live spreadsheet.")
    google_normalize_daily_log_parser.add_argument("--run-output", help="Optional full live normalization run JSON path. Defaults to stdout.")
    google_normalize_daily_log_parser.add_argument("--snapshot-output", help="Optional captured snapshot JSON path.")
    google_normalize_daily_log_parser.add_argument("--report-output", help="Optional Daily Log Results report JSON path.")
    google_normalize_daily_log_parser.add_argument("--audit-output", help="Optional apply audit JSON path.")
    google_normalize_daily_log_parser.add_argument("--batch-output", help="Optional batchUpdate requests JSON path.")

    materialize_parser = subparsers.add_parser(
        "materialize-accepted-plans",
        help="Turn accepted Agent Suggestions into planned Experiments and Results rows.",
    )
    materialize_source = materialize_parser.add_mutually_exclusive_group(required=True)
    materialize_source.add_argument("--workbook", help="Lab notebook .xlsx file.")
    materialize_source.add_argument("--snapshot", help="Google Sheets snapshot JSON file.")
    materialize_parser.add_argument("--suggestion-id", action="append", default=[], help="Accepted suggestion ID to materialize. Repeatable.")
    materialize_parser.add_argument("--planned-date", help="Date to put on generated Experiments rows. Defaults to today.")
    materialize_parser.add_argument("--apply", action="store_true", help="Append generated rows to the workbook.")
    materialize_parser.add_argument("--workbook-output", help="Optional output .xlsx path for workbook apply mode. Defaults to in-place.")
    materialize_parser.add_argument("--report-output", help="Optional materialization report JSON path. Defaults to stdout.")
    materialize_parser.add_argument("--batch-output", help="Optional Google Sheets batchUpdate request JSON path for snapshot mode.")

    scaffold_materials_parser = subparsers.add_parser(
        "scaffold-materials",
        help="Generate process-aware Master Reagents and Formulations starter rows for an experiment.",
    )
    scaffold_materials_source = scaffold_materials_parser.add_mutually_exclusive_group(required=True)
    scaffold_materials_source.add_argument("--workbook", help="Lab notebook .xlsx file.")
    scaffold_materials_source.add_argument("--snapshot", help="Google Sheets snapshot JSON file.")
    scaffold_materials_parser.add_argument("--experiment-id", required=True)
    scaffold_materials_parser.add_argument("--process-type", help="Process type to scaffold. Defaults to the Experiments row process type.")
    scaffold_materials_parser.add_argument("--include-optional", action="store_true", help="Include optional process roles such as crosslinker or chain-transfer agent.")
    scaffold_materials_parser.add_argument("--apply", action="store_true", help="Append generated rows to the workbook.")
    scaffold_materials_parser.add_argument("--workbook-output", help="Optional output .xlsx path for workbook apply mode. Defaults to in-place.")
    scaffold_materials_parser.add_argument("--report-output", help="Optional scaffold report JSON path. Defaults to stdout.")
    scaffold_materials_parser.add_argument("--batch-output", help="Optional Google Sheets batchUpdate request JSON path for snapshot mode.")

    google_materialize_parser = subparsers.add_parser(
        "google-materialize-live",
        help="Capture a live Google Sheet, materialize accepted suggestions, audit, and optionally apply planned rows.",
    )
    google_materialize_parser.add_argument("--spreadsheet-id", required=True)
    google_materialize_parser.add_argument("--service-account-file", help="Optional service account JSON file. Defaults to Application Default Credentials.")
    google_materialize_parser.add_argument("--range", default="A1:Z1000")
    google_materialize_parser.add_argument("--suggestion-id", action="append", default=[], help="Accepted suggestion ID to materialize. Repeatable.")
    google_materialize_parser.add_argument("--planned-date", help="Date to put on generated Experiments rows. Defaults to today.")
    google_materialize_parser.add_argument("--apply", action="store_true", help="Apply valid batchUpdate requests to the live spreadsheet.")
    google_materialize_parser.add_argument("--run-output", help="Optional full live run JSON path. Defaults to stdout.")
    google_materialize_parser.add_argument("--snapshot-output", help="Optional captured snapshot JSON path.")
    google_materialize_parser.add_argument("--report-output", help="Optional materialization report JSON path.")
    google_materialize_parser.add_argument("--audit-output", help="Optional apply audit JSON path.")
    google_materialize_parser.add_argument("--batch-output", help="Optional batchUpdate requests JSON path.")

    args = parser.parse_args(argv)
    if args.command == "init":
        path = save_workbook(args.output, include_examples=not args.no_examples)
        print(path)
        return 0
    if args.command == "search-knowledge":
        records = load_knowledge(args.knowledge)
        results = LocalSemanticIndex(records).search(args.query, k=args.k)
        print_json(
            [
                {
                    "score": round(result.score, 4),
                    "id": result.record.get("id"),
                    "process_type": result.record.get("process_type"),
                    "summary": result.record.get("summary"),
                }
                for result in results
            ]
        )
        return 0
    if args.command == "search-notebook":
        if args.workbook:
            tables = load_workbook_tables(args.workbook)
        else:
            tables = snapshot_to_tables(load_sheet_snapshot(args.snapshot))
        write_or_print_json(
            search_notebook_tables(
                tables,
                args.query,
                k=args.k,
                sheets=tuple(args.sheet),
            ),
            args.output,
        )
        return 0
    if args.command == "search-materials":
        if not args.process_type and not args.experiment_id:
            raise SystemExit("--process-type or --experiment-id is required.")
        if args.workbook:
            tables = load_workbook_tables(args.workbook)
        else:
            tables = snapshot_to_tables(load_sheet_snapshot(args.snapshot))
        write_or_print_json(
            build_process_material_search_report(
                tables,
                process_type=args.process_type,
                experiment_id=args.experiment_id,
                query=args.query,
                k=args.k,
                include_optional=args.include_optional,
            ),
            args.output,
        )
        return 0
    if args.command == "daily-summary":
        if args.workbook:
            tables = load_workbook_tables(args.workbook)
        else:
            tables = snapshot_to_tables(load_sheet_snapshot(args.snapshot))
        write_or_print_json(
            build_daily_summary_report(
                tables,
                review_date=args.review_date,
                experiment_ids=tuple(args.experiment_id),
            ),
            args.output,
        )
        return 0
    if args.command == "experiment-preflight":
        if args.workbook:
            tables = load_workbook_tables(args.workbook)
        else:
            tables = snapshot_to_tables(load_sheet_snapshot(args.snapshot))
        write_or_print_json(
            build_experiment_preflight_report(
                tables,
                experiment_id=args.experiment_id,
                stage=args.stage,
            ),
            args.output,
        )
        return 0
    if args.command == "record-experiment":
        snapshot = None
        audit = None
        record_tables = None
        if args.workbook:
            record_tables = load_workbook_tables(args.workbook)
        elif args.snapshot:
            snapshot = load_sheet_snapshot(args.snapshot)
            record_tables = snapshot_to_tables(snapshot)
        report = build_experiment_record_report(load_experiment_record(args.record), tables=record_tables)
        if args.apply:
            if not args.workbook:
                raise SystemExit("--apply requires --workbook.")
            apply_experiment_record_report_to_workbook(
                args.workbook,
                report,
                output_workbook=args.workbook_output,
            )
        if args.audit_output or args.batch_output:
            if not args.snapshot:
                raise SystemExit("--audit-output and --batch-output require --snapshot so sheet IDs are available.")
            if snapshot is None:
                snapshot = load_sheet_snapshot(args.snapshot)
            audit = audit_report_against_snapshot(report, snapshot, require_sheet_ids=True)
        if args.report_output:
            write_or_print_json(report, args.report_output)
        else:
            print_json(report)
        if args.audit_output and audit is not None:
            write_or_print_json(audit, args.audit_output)
        if args.batch_output and snapshot is not None and audit is not None:
            requests = batch_update_requests_from_report(report, sheet_ids_from_snapshot(snapshot)) if audit["valid"] else []
            write_or_print_json(requests, args.batch_output)
        return 0
    if args.command == "record-daily-agent-run":
        config = AgentRunConfig(
            experiment_ids=tuple(args.experiment_id),
            review_date=args.review_date,
            context_limit=args.context_limit,
            history_limit=args.history_limit,
            evidence_limit=args.evidence_limit,
            force=args.force,
            litscout_export=args.litscout_export,
            run_litscout=args.run_litscout,
            litscout_sources=args.litscout_sources,
            litscout_depth=args.litscout_depth,
            litscout_limit=args.litscout_limit,
            artifacts_dir=args.artifacts_dir,
        )
        record = load_experiment_record(args.record)
        if args.workbook:
            if args.audit_output or args.batch_output:
                raise SystemExit("--audit-output and --batch-output require --snapshot so sheet IDs are available.")
            run = run_workbook_recorded_daily_agent(
                args.workbook,
                record,
                config,
                apply=args.apply,
                output_workbook=args.workbook_output,
            )
        else:
            if args.apply:
                raise SystemExit("--apply is only available with --workbook. Use --batch-output for snapshots.")
            run = build_snapshot_recorded_daily_agent_run(load_sheet_snapshot(args.snapshot), record, config)
        write_recorded_daily_outputs(
            run,
            run_output=args.run_output,
            record_output=args.record_output,
            daily_run_output=args.daily_run_output,
            audit_output=args.audit_output,
            batch_output=args.batch_output,
        )
        return 0
    if args.command == "normalize-daily-log-results":
        if args.workbook:
            tables = load_workbook_tables(args.workbook)
        else:
            snapshot = load_sheet_snapshot(args.snapshot)
            tables = snapshot_to_tables(snapshot)
        report = build_daily_log_results_report(
            tables,
            experiment_ids=tuple(args.experiment_id),
            review_date=args.review_date,
        )
        if args.apply:
            if not args.workbook:
                raise SystemExit("--apply is only available with --workbook. Use --batch-output for snapshots.")
            apply_daily_log_results_report_to_workbook(
                args.workbook,
                report,
                output_workbook=args.workbook_output,
            )
        if args.report_output:
            write_or_print_json(report, args.report_output)
        else:
            print_json(report)
        if args.batch_output:
            if not args.snapshot:
                raise SystemExit("--batch-output requires --snapshot so sheet IDs are available.")
            requests = batch_update_requests_from_report(report, sheet_ids_from_snapshot(snapshot))
            write_or_print_json(requests, args.batch_output)
        return 0
    if args.command == "normalize-formulations":
        if args.workbook:
            tables = load_workbook_tables(args.workbook)
        else:
            snapshot = load_sheet_snapshot(args.snapshot)
            tables = snapshot_to_tables(snapshot)
        report = build_formulation_normalization_report(
            tables,
            experiment_ids=tuple(args.experiment_id),
        )
        if args.apply:
            if not args.workbook:
                raise SystemExit("--apply is only available with --workbook. Use --batch-output for snapshots.")
            apply_formulation_normalization_report_to_workbook(
                args.workbook,
                report,
                output_workbook=args.workbook_output,
            )
        if args.report_output:
            write_or_print_json(report, args.report_output)
        else:
            print_json(report)
        if args.batch_output:
            if not args.snapshot:
                raise SystemExit("--batch-output requires --snapshot so sheet IDs are available.")
            requests = batch_update_requests_from_report(report, sheet_ids_from_snapshot(snapshot))
            write_or_print_json(requests, args.batch_output)
        return 0
    if args.command == "daily-agent-run":
        config = AgentRunConfig(
            experiment_ids=tuple(args.experiment_id),
            review_date=args.review_date,
            context_limit=args.context_limit,
            history_limit=args.history_limit,
            evidence_limit=args.evidence_limit,
            force=args.force,
            litscout_export=args.litscout_export,
            run_litscout=args.run_litscout,
            litscout_sources=args.litscout_sources,
            litscout_depth=args.litscout_depth,
            litscout_limit=args.litscout_limit,
            artifacts_dir=args.artifacts_dir,
        )
        if args.workbook:
            if args.audit_output or args.batch_output:
                raise SystemExit("--audit-output and --batch-output require --snapshot so sheet IDs are available.")
            run = run_workbook_daily_agent(
                args.workbook,
                config=config,
                apply=args.apply,
                output_workbook=args.workbook_output,
            )
        else:
            if args.apply:
                raise SystemExit("--apply is only available with --workbook. Use --batch-output for snapshots.")
            snapshot = load_sheet_snapshot(args.snapshot)
            run = build_snapshot_daily_agent_run(snapshot, config=config)
        write_daily_agent_outputs(
            run,
            run_output=args.run_output,
            summary_output=args.summary_output,
            report_output=args.report_output,
            audit_output=args.audit_output,
            batch_output=args.batch_output,
        )
        return 0
    if args.command == "schema":
        contract = workbook_contract()
        if args.output:
            output = Path(args.output).expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
            print(output)
        else:
            print_json(contract)
        return 0
    if args.command == "suggest":
        records = load_knowledge(args.knowledge)
        suggestion = build_recommendation(load_entry(args.entry), LocalSemanticIndex(records))
        write_or_print_json(suggestion, args.output)
        return 0
    if args.command == "audit-entry":
        write_or_print_json(audit_experiment_materials(load_entry(args.entry)), args.output)
        return 0
    if args.command == "entry-from-workbook":
        output = save_entry_from_workbook(args.workbook, args.experiment_id, args.output)
        print(output)
        return 0
    if args.command == "suggest-workbook":
        records = load_knowledge(args.knowledge)
        suggestion = suggest_from_workbook(args.workbook, args.experiment_id, LocalSemanticIndex(records))
        if args.append_to_workbook:
            appended = append_suggestion_to_workbook(args.workbook, suggestion, args.append_to_workbook)
            print(appended)
        else:
            write_or_print_json(suggestion, args.output)
        return 0
    if args.command == "audit-workbook":
        from .sheets import build_experiment_entry_from_tables

        tables = load_workbook_tables(args.workbook)
        write_or_print_json(audit_experiment_materials(build_experiment_entry_from_tables(tables, args.experiment_id)), args.output)
        return 0
    if args.command == "evidence-from-litscout":
        works = load_litscout_export(args.input)
        rows = litscout_works_to_evidence_rows(works, args.experiment_id, args.query, limit=args.limit)
        payload = evidence_rows_to_values(rows) if args.values else rows
        write_or_print_json(payload, args.output)
        return 0
    if args.command == "agent-run":
        config = AgentRunConfig(
            experiment_ids=tuple(args.experiment_id),
            review_date=args.review_date,
            context_limit=args.context_limit,
            history_limit=args.history_limit,
            evidence_limit=args.evidence_limit,
            force=args.force,
            litscout_export=args.litscout_export,
            run_litscout=args.run_litscout,
            litscout_sources=args.litscout_sources,
            litscout_depth=args.litscout_depth,
            litscout_limit=args.litscout_limit,
            artifacts_dir=args.artifacts_dir,
        )
        report = run_workbook_agent(
            args.workbook,
            config=config,
            apply=args.apply,
            output_workbook=args.workbook_output,
            report_path=args.report_output,
        )
        if not args.report_output:
            print_json(report)
        else:
            print(Path(args.report_output).expanduser().resolve())
        return 0
    if args.command == "google-batch-from-report":
        report = load_agent_report(args.report)
        sheet_ids = {}
        if args.master_reagents_sheet_id is not None:
            sheet_ids["Master Reagents"] = args.master_reagents_sheet_id
        if args.experiments_sheet_id is not None:
            sheet_ids["Experiments"] = args.experiments_sheet_id
        if args.formulations_sheet_id is not None:
            sheet_ids["Formulations"] = args.formulations_sheet_id
        if args.results_sheet_id is not None:
            sheet_ids["Results"] = args.results_sheet_id
        if args.literature_evidence_sheet_id is not None:
            sheet_ids["Literature Evidence"] = args.literature_evidence_sheet_id
        if args.agent_suggestions_sheet_id is not None:
            sheet_ids["Agent Suggestions"] = args.agent_suggestions_sheet_id
        if args.daily_reviews_sheet_id is not None:
            sheet_ids["Daily Reviews"] = args.daily_reviews_sheet_id
        requests = batch_update_requests_from_report(report, sheet_ids)
        write_or_print_json(requests, args.output)
        return 0
    if args.command == "agent-run-snapshot":
        snapshot = load_sheet_snapshot(args.snapshot)
        tables = snapshot_to_tables(snapshot)
        config = AgentRunConfig(
            experiment_ids=tuple(args.experiment_id),
            review_date=args.review_date,
            context_limit=args.context_limit,
            history_limit=args.history_limit,
            evidence_limit=args.evidence_limit,
            force=args.force,
            litscout_export=args.litscout_export,
            run_litscout=args.run_litscout,
            litscout_sources=args.litscout_sources,
            litscout_depth=args.litscout_depth,
            litscout_limit=args.litscout_limit,
            artifacts_dir=args.artifacts_dir,
        )
        report = build_agent_report(tables, config=config)
        if args.report_output:
            write_or_print_json(report, args.report_output)
        else:
            print_json(report)
        if args.batch_output:
            requests = batch_update_requests_from_report(report, sheet_ids_from_snapshot(snapshot))
            write_or_print_json(requests, args.batch_output)
        return 0
    if args.command == "snapshot-from-workbook":
        from .google_sheets import snapshot_from_tables

        snapshot = snapshot_from_tables(load_workbook_tables(args.workbook), parse_sheet_id_args(args.sheet_id))
        write_or_print_json(snapshot, args.output)
        return 0
    if args.command == "validate-snapshot":
        snapshot = load_sheet_snapshot(args.snapshot)
        if args.report:
            audit = audit_report_against_snapshot(
                load_agent_report(args.report),
                snapshot,
                require_sheet_ids=args.require_sheet_ids,
            )
        else:
            audit = validate_snapshot(snapshot, require_sheet_ids=args.require_sheet_ids)
        write_or_print_json(audit, args.output)
        return 0
    if args.command == "google-capture-plan":
        write_or_print_json(snapshot_capture_plan(args.spreadsheet_id, args.range), args.output)
        return 0
    if args.command == "google-snapshot":
        client = build_google_client(args.service_account_file)
        snapshot = capture_snapshot_from_google_sheets(
            args.spreadsheet_id,
            client,
            value_range=args.range,
        )
        write_or_print_json(snapshot, args.output)
        return 0
    if args.command == "google-doctor":
        write_or_print_json(
            google_api_doctor(
                spreadsheet_id=args.spreadsheet_id,
                service_account_file=args.service_account_file,
            ),
            args.output,
        )
        return 0
    if args.command == "google-setup-live":
        client = build_google_client(args.service_account_file)
        run = run_live_google_setup(
            args.spreadsheet_id,
            client,
            apply=args.apply,
            include_validations=not args.no_validations,
            validation_end_row=args.validation_end_row,
        )
        if args.metadata_output:
            write_or_print_json(run.get("metadata", {}), args.metadata_output)
        if args.audit_output:
            write_or_print_json(run.get("setup_audit", {}), args.audit_output)
        if args.batch_output:
            write_or_print_json(run.get("batch_update_requests", []), args.batch_output)
        if args.run_output:
            write_or_print_json(run, args.run_output)
        elif not any([args.metadata_output, args.audit_output, args.batch_output]):
            print_json(run)
        return 0
    if args.command == "materialize-accepted-plans":
        if args.workbook:
            tables = load_workbook_tables(args.workbook)
        else:
            snapshot = load_sheet_snapshot(args.snapshot)
            tables = snapshot_to_tables(snapshot)
        report = build_plan_materialization_report(
            tables,
            planned_date=args.planned_date,
            suggestion_ids=tuple(args.suggestion_id),
        )
        if args.apply:
            if not args.workbook:
                raise SystemExit("--apply is only available with --workbook. Use --batch-output for snapshots.")
            apply_plan_materialization_report_to_workbook(
                args.workbook,
                report,
                output_workbook=args.workbook_output,
            )
        if args.report_output:
            write_or_print_json(report, args.report_output)
        else:
            print_json(report)
        if args.batch_output:
            if not args.snapshot:
                raise SystemExit("--batch-output requires --snapshot so sheet IDs are available.")
            requests = batch_update_requests_from_report(report, sheet_ids_from_snapshot(snapshot))
            write_or_print_json(requests, args.batch_output)
        return 0
    if args.command == "scaffold-materials":
        if args.workbook:
            tables = load_workbook_tables(args.workbook)
        else:
            snapshot = load_sheet_snapshot(args.snapshot)
            tables = snapshot_to_tables(snapshot)
        report = build_material_scaffold_report(
            tables,
            experiment_id=args.experiment_id,
            process_type=args.process_type,
            include_optional=args.include_optional,
        )
        if args.apply:
            if not args.workbook:
                raise SystemExit("--apply is only available with --workbook. Use --batch-output for snapshots.")
            apply_material_scaffold_report_to_workbook(
                args.workbook,
                report,
                output_workbook=args.workbook_output,
            )
        if args.report_output:
            write_or_print_json(report, args.report_output)
        else:
            print_json(report)
        if args.batch_output:
            if not args.snapshot:
                raise SystemExit("--batch-output requires --snapshot so sheet IDs are available.")
            requests = batch_update_requests_from_report(report, sheet_ids_from_snapshot(snapshot))
            write_or_print_json(requests, args.batch_output)
        return 0
    if args.command == "google-agent-run-live":
        client = build_google_client(args.service_account_file)
        config = AgentRunConfig(
            experiment_ids=tuple(args.experiment_id),
            review_date=args.review_date,
            context_limit=args.context_limit,
            history_limit=args.history_limit,
            evidence_limit=args.evidence_limit,
            force=args.force,
            litscout_export=args.litscout_export,
            run_litscout=args.run_litscout,
            litscout_sources=args.litscout_sources,
            litscout_depth=args.litscout_depth,
            litscout_limit=args.litscout_limit,
            artifacts_dir=args.artifacts_dir,
        )
        run = run_live_google_agent(
            args.spreadsheet_id,
            client,
            config=config,
            value_range=args.range,
            apply=args.apply,
        )
        write_live_run_outputs(
            run,
            run_output=args.run_output,
            snapshot_output=args.snapshot_output,
            report_output=args.report_output,
            audit_output=args.audit_output,
            batch_output=args.batch_output,
            report_key="agent_report",
        )
        return 0
    if args.command == "google-record-experiment-live":
        client = build_google_client(args.service_account_file)
        run = run_live_google_experiment_record(
            args.spreadsheet_id,
            client,
            load_experiment_record(args.record),
            value_range=args.range,
            apply=args.apply,
        )
        write_live_run_outputs(
            run,
            run_output=args.run_output,
            snapshot_output=args.snapshot_output,
            report_output=args.report_output,
            audit_output=args.audit_output,
            batch_output=args.batch_output,
            report_key="record_report",
        )
        return 0
    if args.command == "google-record-daily-agent-run-live":
        client = build_google_client(args.service_account_file)
        config = AgentRunConfig(
            experiment_ids=tuple(args.experiment_id),
            review_date=args.review_date,
            context_limit=args.context_limit,
            history_limit=args.history_limit,
            evidence_limit=args.evidence_limit,
            force=args.force,
            litscout_export=args.litscout_export,
            run_litscout=args.run_litscout,
            litscout_sources=args.litscout_sources,
            litscout_depth=args.litscout_depth,
            litscout_limit=args.litscout_limit,
            artifacts_dir=args.artifacts_dir,
        )
        run = run_live_google_recorded_daily_agent(
            args.spreadsheet_id,
            client,
            load_experiment_record(args.record),
            config=config,
            value_range=args.range,
            apply=args.apply,
        )
        write_live_recorded_daily_outputs(
            run,
            run_output=args.run_output,
            snapshot_output=args.snapshot_output,
            record_output=args.record_output,
            daily_run_output=args.daily_run_output,
            audit_output=args.audit_output,
            batch_output=args.batch_output,
        )
        return 0
    if args.command == "google-daily-agent-run-live":
        client = build_google_client(args.service_account_file)
        config = AgentRunConfig(
            experiment_ids=tuple(args.experiment_id),
            review_date=args.review_date,
            context_limit=args.context_limit,
            history_limit=args.history_limit,
            evidence_limit=args.evidence_limit,
            force=args.force,
            litscout_export=args.litscout_export,
            run_litscout=args.run_litscout,
            litscout_sources=args.litscout_sources,
            litscout_depth=args.litscout_depth,
            litscout_limit=args.litscout_limit,
            artifacts_dir=args.artifacts_dir,
        )
        run = run_live_google_daily_agent(
            args.spreadsheet_id,
            client,
            config=config,
            value_range=args.range,
            apply=args.apply,
        )
        write_live_daily_agent_outputs(
            run,
            run_output=args.run_output,
            snapshot_output=args.snapshot_output,
            daily_run_output=args.daily_run_output,
            summary_output=args.summary_output,
            report_output=args.report_output,
            audit_output=args.audit_output,
            batch_output=args.batch_output,
        )
        return 0
    if args.command == "google-normalize-formulations-live":
        client = build_google_client(args.service_account_file)
        run = run_live_google_formulation_normalization(
            args.spreadsheet_id,
            client,
            experiment_ids=tuple(args.experiment_id),
            value_range=args.range,
            apply=args.apply,
        )
        write_live_run_outputs(
            run,
            run_output=args.run_output,
            snapshot_output=args.snapshot_output,
            report_output=args.report_output,
            audit_output=args.audit_output,
            batch_output=args.batch_output,
            report_key="formulation_normalization_report",
        )
        return 0
    if args.command == "google-normalize-daily-log-results-live":
        client = build_google_client(args.service_account_file)
        run = run_live_google_daily_log_results_normalization(
            args.spreadsheet_id,
            client,
            experiment_ids=tuple(args.experiment_id),
            review_date=args.review_date,
            value_range=args.range,
            apply=args.apply,
        )
        write_live_run_outputs(
            run,
            run_output=args.run_output,
            snapshot_output=args.snapshot_output,
            report_output=args.report_output,
            audit_output=args.audit_output,
            batch_output=args.batch_output,
            report_key="daily_log_results_report",
        )
        return 0
    if args.command == "google-materialize-live":
        client = build_google_client(args.service_account_file)
        run = run_live_google_plan_materialization(
            args.spreadsheet_id,
            client,
            planned_date=args.planned_date,
            suggestion_ids=tuple(args.suggestion_id),
            value_range=args.range,
            apply=args.apply,
        )
        write_live_run_outputs(
            run,
            run_output=args.run_output,
            snapshot_output=args.snapshot_output,
            report_output=args.report_output,
            audit_output=args.audit_output,
            batch_output=args.batch_output,
            report_key="materialization_report",
        )
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


def print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def write_or_print_json(value: Any, output_path: str | None) -> None:
    if output_path:
        output = Path(output_path).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        print(output)
    else:
        print_json(value)


def parse_sheet_id_args(values: list[str]) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Sheet ID mapping must be 'Sheet Name=123', got {value!r}.")
        name, raw_id = value.rsplit("=", 1)
        parsed[name.strip()] = int(raw_id.strip())
    return parsed


def build_google_client(service_account_file: str | None) -> GoogleSheetsApiClient:
    try:
        return GoogleSheetsApiClient.from_credentials(
            GoogleCredentialsConfig(service_account_file=service_account_file)
        )
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc


def write_daily_agent_outputs(
    run: dict[str, Any],
    run_output: str | None,
    summary_output: str | None,
    report_output: str | None,
    audit_output: str | None,
    batch_output: str | None,
) -> None:
    if summary_output:
        write_or_print_json(run.get("daily_summary", {}), summary_output)
    if report_output:
        write_or_print_json(run.get("agent_report", {}), report_output)
    if audit_output:
        write_or_print_json(run.get("apply_audit", {}), audit_output)
    if batch_output:
        write_or_print_json(run.get("batch_update_requests", []), batch_output)
    if run_output:
        write_or_print_json(run, run_output)
    elif not any([summary_output, report_output, audit_output, batch_output]):
        print_json(run)


def write_live_daily_agent_outputs(
    run: dict[str, Any],
    run_output: str | None,
    snapshot_output: str | None,
    daily_run_output: str | None,
    summary_output: str | None,
    report_output: str | None,
    audit_output: str | None,
    batch_output: str | None,
) -> None:
    if snapshot_output:
        write_or_print_json(run.get("snapshot", {}), snapshot_output)
    if daily_run_output:
        write_or_print_json(run.get("daily_agent_run", {}), daily_run_output)
    if summary_output:
        write_or_print_json(run.get("daily_summary", {}), summary_output)
    if report_output:
        write_or_print_json(run.get("agent_report", {}), report_output)
    if audit_output:
        write_or_print_json(run.get("apply_audit", {}), audit_output)
    if batch_output:
        write_or_print_json(run.get("batch_update_requests", []), batch_output)
    if run_output:
        write_or_print_json(run, run_output)
    elif not any([snapshot_output, daily_run_output, summary_output, report_output, audit_output, batch_output]):
        print_json(run)


def write_recorded_daily_outputs(
    run: dict[str, Any],
    run_output: str | None,
    record_output: str | None,
    daily_run_output: str | None,
    audit_output: str | None,
    batch_output: str | None,
) -> None:
    if record_output:
        write_or_print_json(run.get("record_report", {}), record_output)
    if daily_run_output:
        write_or_print_json(run.get("daily_agent_run", {}), daily_run_output)
    if audit_output:
        write_or_print_json(run.get("apply_audit", {}), audit_output)
    if batch_output:
        write_or_print_json(run.get("batch_update_requests", []), batch_output)
    if run_output:
        write_or_print_json(run, run_output)
    elif not any([record_output, daily_run_output, audit_output, batch_output]):
        print_json(run)


def write_live_recorded_daily_outputs(
    run: dict[str, Any],
    run_output: str | None,
    snapshot_output: str | None,
    record_output: str | None,
    daily_run_output: str | None,
    audit_output: str | None,
    batch_output: str | None,
) -> None:
    if snapshot_output:
        write_or_print_json(run.get("snapshot", {}), snapshot_output)
    if record_output:
        write_or_print_json(run.get("record_report", {}), record_output)
    if daily_run_output:
        write_or_print_json(run.get("daily_agent_run", {}), daily_run_output)
    if audit_output:
        write_or_print_json(run.get("apply_audit", {}), audit_output)
    if batch_output:
        write_or_print_json(run.get("batch_update_requests", []), batch_output)
    if run_output:
        write_or_print_json(run, run_output)
    elif not any([snapshot_output, record_output, daily_run_output, audit_output, batch_output]):
        print_json(run)


def write_live_run_outputs(
    run: dict[str, Any],
    run_output: str | None,
    snapshot_output: str | None,
    report_output: str | None,
    audit_output: str | None,
    batch_output: str | None,
    report_key: str,
) -> None:
    if snapshot_output:
        write_or_print_json(run.get("snapshot", {}), snapshot_output)
    if report_output:
        write_or_print_json(run.get(report_key, {}), report_output)
    if audit_output:
        write_or_print_json(run.get("apply_audit", {}), audit_output)
    if batch_output:
        write_or_print_json(run.get("batch_update_requests", []), batch_output)
    if run_output:
        write_or_print_json(run, run_output)
    elif not any([snapshot_output, report_output, audit_output, batch_output]):
        print_json(run)


if __name__ == "__main__":
    raise SystemExit(main())
