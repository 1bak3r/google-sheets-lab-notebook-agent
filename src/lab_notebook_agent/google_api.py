from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

from .agent import AgentRunConfig, build_agent_report
from .daily_agent import build_snapshot_daily_agent_run
from .google_sheets import (
    audit_report_against_snapshot,
    batch_update_requests_from_report,
    sheet_ids_from_snapshot,
    snapshot_to_tables,
    validate_snapshot,
)
from .planning import build_plan_materialization_report
from .schema import SHEETS


DEFAULT_SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
)


class SheetsApiClient(Protocol):
    def get_metadata(self, spreadsheet_id: str) -> dict[str, Any]:
        ...

    def get_values(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        value_range: str,
        value_render_option: str = "FORMATTED_VALUE",
    ) -> list[list[Any]]:
        ...

    def batch_update(self, spreadsheet_id: str, requests: list[dict[str, Any]]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class GoogleCredentialsConfig:
    service_account_file: str | None = None
    scopes: tuple[str, ...] = DEFAULT_SCOPES


class GoogleSheetsApiClient:
    def __init__(self, session: Any, base_url: str = "https://sheets.googleapis.com") -> None:
        self.session = session
        self.base_url = base_url.rstrip("/")

    @classmethod
    def from_credentials(cls, config: GoogleCredentialsConfig | None = None) -> "GoogleSheetsApiClient":
        config = config or GoogleCredentialsConfig()
        try:
            import google.auth
            from google.auth.exceptions import DefaultCredentialsError
            from google.auth.transport.requests import AuthorizedSession
            from google.oauth2 import service_account
        except ImportError as exc:
            raise RuntimeError(
                "Google API support requires optional dependencies. Install with "
                "`pip install -e .[google]` or install google-auth and requests."
            ) from exc

        try:
            if config.service_account_file:
                credentials = service_account.Credentials.from_service_account_file(
                    str(Path(config.service_account_file).expanduser()),
                    scopes=list(config.scopes),
                )
            else:
                credentials, _ = google.auth.default(scopes=list(config.scopes))
        except (DefaultCredentialsError, FileNotFoundError, ValueError) as exc:
            raise RuntimeError(f"Google credentials are not ready: {exc}") from exc
        return cls(AuthorizedSession(credentials))

    def get_metadata(self, spreadsheet_id: str) -> dict[str, Any]:
        return self.request_json(
            "GET",
            f"/v4/spreadsheets/{spreadsheet_id}",
            params={"fields": "spreadsheetId,properties(title),sheets(properties(sheetId,title,gridProperties))"},
        )

    def get_values(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        value_range: str,
        value_render_option: str = "FORMATTED_VALUE",
    ) -> list[list[Any]]:
        a1_range = f"{quote_sheet_name(sheet_name)}!{value_range}"
        payload = self.request_json(
            "GET",
            f"/v4/spreadsheets/{spreadsheet_id}/values/{quote(a1_range, safe='')}",
            params={"valueRenderOption": value_render_option},
        )
        values = payload.get("values", [])
        return values if isinstance(values, list) else []

    def batch_update(self, spreadsheet_id: str, requests: list[dict[str, Any]]) -> dict[str, Any]:
        return self.request_json(
            "POST",
            f"/v4/spreadsheets/{spreadsheet_id}:batchUpdate",
            body={"requests": requests},
        )

    def request_json(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self.session.request(
            method,
            f"{self.base_url}{path}",
            params=params,
            json=body,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Google Sheets API response was not a JSON object.")
        return payload


def capture_snapshot_from_google_sheets(
    spreadsheet_id: str,
    client: SheetsApiClient,
    value_range: str = "A1:Z1000",
    value_render_option: str = "FORMATTED_VALUE",
) -> dict[str, Any]:
    metadata = client.get_metadata(spreadsheet_id)
    sheet_ids = sheet_ids_from_metadata(metadata)
    sheets: dict[str, Any] = {}
    for spec in SHEETS:
        sheets[spec.name] = {
            "sheet_id": sheet_ids.get(spec.name),
            "values": client.get_values(
                spreadsheet_id,
                spec.name,
                value_range,
                value_render_option=value_render_option,
            ),
        }
    return {
        "schema": "lab-notebook-agent-google-sheets-snapshot.v1",
        "spreadsheet_id": spreadsheet_id,
        "sheets": sheets,
    }


def run_live_google_agent(
    spreadsheet_id: str,
    client: SheetsApiClient,
    config: AgentRunConfig | None = None,
    value_range: str = "A1:Z1000",
    apply: bool = False,
) -> dict[str, Any]:
    snapshot = capture_snapshot_from_google_sheets(spreadsheet_id, client, value_range=value_range)
    snapshot_audit = validate_snapshot(snapshot, require_sheet_ids=False)
    if snapshot_audit["valid"]:
        report = build_agent_report(snapshot_to_tables(snapshot), config=config)
    else:
        report = {
            "schema": "lab-notebook-agent-run.v1",
            "summary": {},
            "runs": [],
        }
    apply_audit = audit_report_against_snapshot(report, snapshot, require_sheet_ids=True)
    requests = batch_update_requests_from_report(report, sheet_ids_from_snapshot(snapshot)) if apply_audit["valid"] else []
    response = client.batch_update(spreadsheet_id, requests) if apply and requests else {}
    return {
        "schema": "lab-notebook-agent-live-google-run.v1",
        "spreadsheet_id": spreadsheet_id,
        "applied": bool(apply and requests),
        "snapshot": snapshot,
        "snapshot_audit": snapshot_audit,
        "agent_report": report,
        "apply_audit": apply_audit,
        "batch_update_requests": requests,
        "batch_update_response": response,
    }


def run_live_google_daily_agent(
    spreadsheet_id: str,
    client: SheetsApiClient,
    config: AgentRunConfig,
    value_range: str = "A1:Z1000",
    apply: bool = False,
) -> dict[str, Any]:
    snapshot = capture_snapshot_from_google_sheets(spreadsheet_id, client, value_range=value_range)
    daily_run = build_snapshot_daily_agent_run(snapshot, config)
    requests = daily_run.get("batch_update_requests", [])
    response = client.batch_update(spreadsheet_id, requests) if apply and requests else {}
    return {
        "schema": "lab-notebook-agent-live-google-daily-run.v1",
        "spreadsheet_id": spreadsheet_id,
        "applied": bool(apply and requests),
        "snapshot": snapshot,
        "snapshot_audit": daily_run.get("snapshot_audit", {}),
        "daily_agent_run": daily_run,
        "daily_summary": daily_run.get("daily_summary", {}),
        "agent_report": daily_run.get("agent_report", {}),
        "apply_audit": daily_run.get("apply_audit", {}),
        "batch_update_requests": requests,
        "batch_update_response": response,
    }


def run_live_google_plan_materialization(
    spreadsheet_id: str,
    client: SheetsApiClient,
    planned_date: str | None = None,
    suggestion_ids: tuple[str, ...] = (),
    value_range: str = "A1:Z1000",
    apply: bool = False,
) -> dict[str, Any]:
    snapshot = capture_snapshot_from_google_sheets(spreadsheet_id, client, value_range=value_range)
    snapshot_audit = validate_snapshot(snapshot, require_sheet_ids=False)
    if snapshot_audit["valid"]:
        report = build_plan_materialization_report(
            snapshot_to_tables(snapshot),
            planned_date=planned_date,
            suggestion_ids=suggestion_ids,
        )
    else:
        report = {
            "schema": "lab-notebook-agent-plan-materialization.v1",
            "summary": {},
            "runs": [],
        }
    apply_audit = audit_report_against_snapshot(report, snapshot, require_sheet_ids=True)
    requests = batch_update_requests_from_report(report, sheet_ids_from_snapshot(snapshot)) if apply_audit["valid"] else []
    response = client.batch_update(spreadsheet_id, requests) if apply and requests else {}
    return {
        "schema": "lab-notebook-agent-live-google-plan-materialization.v1",
        "spreadsheet_id": spreadsheet_id,
        "applied": bool(apply and requests),
        "snapshot": snapshot,
        "snapshot_audit": snapshot_audit,
        "materialization_report": report,
        "apply_audit": apply_audit,
        "batch_update_requests": requests,
        "batch_update_response": response,
    }


def google_api_doctor(
    spreadsheet_id: str | None = None,
    service_account_file: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema": "lab-notebook-agent-google-api-doctor.v1",
        "checks": [],
        "ready": False,
    }
    try:
        client = GoogleSheetsApiClient.from_credentials(
            GoogleCredentialsConfig(service_account_file=service_account_file)
        )
    except RuntimeError as exc:
        result["checks"].append(
            {
                "name": "credentials",
                "status": "failed",
                "message": str(exc),
            }
        )
        return result

    result["checks"].append(
        {
            "name": "credentials",
            "status": "passed",
            "message": "Google API credentials loaded.",
        }
    )
    if not spreadsheet_id:
        result["ready"] = True
        return result

    try:
        metadata = client.get_metadata(spreadsheet_id)
    except Exception as exc:  # pragma: no cover - provider-specific transport details.
        result["checks"].append(
            {
                "name": "spreadsheet_metadata",
                "status": "failed",
                "message": str(exc),
            }
        )
        return result

    sheet_ids = sheet_ids_from_metadata(metadata)
    missing_sheets = [spec.name for spec in SHEETS if spec.name not in sheet_ids]
    if missing_sheets:
        result["checks"].append(
            {
                "name": "spreadsheet_contract",
                "status": "failed",
                "missing_sheets": missing_sheets,
            }
        )
        return result

    result["checks"].append(
        {
            "name": "spreadsheet_contract",
            "status": "passed",
            "sheet_count": len(sheet_ids),
        }
    )
    result["ready"] = True
    return result


def sheet_ids_from_metadata(metadata: dict[str, Any]) -> dict[str, int]:
    ids: dict[str, int] = {}
    for sheet in metadata.get("sheets", []) or []:
        if not isinstance(sheet, dict):
            continue
        properties = sheet.get("properties", {})
        if not isinstance(properties, dict):
            continue
        title = properties.get("title")
        sheet_id = properties.get("sheetId")
        if title is not None and sheet_id is not None:
            ids[str(title)] = int(sheet_id)
    return ids


def quote_sheet_name(sheet_name: str) -> str:
    return "'" + sheet_name.replace("'", "''") + "'"
