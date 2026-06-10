# Live Google Sheets Workflow

This runbook connects the local lab notebook agent to a Google Sheet without
changing the core agent logic.

## Current Live Sheet

- Spreadsheet ID: `1swzNI5YXruBwl0KgoG3b0hrmD12GopLf71YfKHs4AM8`
- URL: `https://docs.google.com/spreadsheets/d/1swzNI5YXruBwl0KgoG3b0hrmD12GopLf71YfKHs4AM8`
- Append target sheet IDs:
  - `Master Reagents`: recapture from spreadsheet metadata before applying starter rows
- `Formulations`: recapture from spreadsheet metadata before applying starter rows or accepted plans
  - `Literature Evidence`: `1198739748`
  - `Agent Suggestions`: `89758567`
  - `Experiments`: recapture from spreadsheet metadata before applying accepted plans
  - `Results`: recapture from spreadsheet metadata before applying accepted plans or daily normalized measurements
  - `Daily Reviews`: recapture from spreadsheet metadata before applying daily review rows

The Google connector last returned `token_expired`; re-authenticate the Drive /
Sheets connector before attempting fresh live reads or writes.

If the connector is unavailable, the local CLI can use the Google Sheets API
directly with Application Default Credentials or a service account:

```bash
pip install -e .[google]
```

If `pip` is blocked by a Debian/Ubuntu externally managed Python and a virtual
environment is not available, use an ignored local dependency directory:

```bash
python3 -m pip install --target .python-deps/google google-auth requests
```

## 1. Generate The Capture Plan

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli google-capture-plan \
  --spreadsheet-id 1swzNI5YXruBwl0KgoG3b0hrmD12GopLf71YfKHs4AM8 \
  --output artifacts/google-capture-plan.json
```

The plan lists every tab and the `A1:Z1000` range to read with the Google
Sheets connector.

## Direct API Alternative

Capture, run, audit, and emit batch requests directly:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli google-doctor \
  --spreadsheet-id 1swzNI5YXruBwl0KgoG3b0hrmD12GopLf71YfKHs4AM8 \
  --output artifacts/google-doctor.json

PYTHONPATH=src python3 -m lab_notebook_agent.cli google-agent-run-live \
  --spreadsheet-id 1swzNI5YXruBwl0KgoG3b0hrmD12GopLf71YfKHs4AM8 \
  --review-date 2026-06-09 \
  --litscout-export artifacts/litscout-ep-001.json \
  --snapshot-output artifacts/live-google-snapshot.json \
  --report-output artifacts/live-google-agent-run.json \
  --audit-output artifacts/live-google-agent-audit.json \
  --batch-output artifacts/live-google-agent-batch.json
```

For the combined daily review against the live sheet, use:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli google-daily-agent-run-live \
  --spreadsheet-id 1swzNI5YXruBwl0KgoG3b0hrmD12GopLf71YfKHs4AM8 \
  --review-date 2026-06-09 \
  --litscout-export artifacts/litscout-ep-001.json \
  --snapshot-output artifacts/live-google-daily-snapshot.json \
  --daily-run-output artifacts/live-google-daily-agent-run.json \
  --summary-output artifacts/live-google-daily-summary.json \
  --report-output artifacts/live-google-agent-run.json \
  --audit-output artifacts/live-google-agent-audit.json \
  --batch-output artifacts/live-google-agent-batch.json
```

Add `--apply` only after checking that the audit is valid. The command uses
Application Default Credentials unless `--service-account-file path/to/key.json`
is provided. The service account or ADC principal must have edit access to the
spreadsheet.

When using the local target dependency directory, prefix the commands with
`PYTHONPATH=.python-deps/google:src` instead of `PYTHONPATH=src`.

Accepted plans can be materialized directly too:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli google-materialize-live \
  --spreadsheet-id 1swzNI5YXruBwl0KgoG3b0hrmD12GopLf71YfKHs4AM8 \
  --planned-date 2026-06-10 \
  --snapshot-output artifacts/live-google-plan-snapshot.json \
  --report-output artifacts/live-google-plan-materialization.json \
  --audit-output artifacts/live-google-plan-audit.json \
  --batch-output artifacts/live-google-plan-batch.json
```

## 2. Capture A Snapshot

For each plan entry, read the tab range through the connector using:

- `spreadsheet_id`: `1swzNI5YXruBwl0KgoG3b0hrmD12GopLf71YfKHs4AM8`
- `sheet_name`: tab name from the plan
- `range`: `A1:Z1000`
- `value_render_option`: `FORMATTED_VALUE`

Write the collected values to:

```json
{
  "schema": "lab-notebook-agent-google-sheets-snapshot.v1",
  "spreadsheet_id": "1swzNI5YXruBwl0KgoG3b0hrmD12GopLf71YfKHs4AM8",
  "sheets": {
    "Experiments": {
      "sheet_id": 1318498454,
      "values": [["experiment_id", "..."], ["EP-001", "..."]]
    }
  }
}
```

`Literature Evidence` and `Agent Suggestions` need `sheet_id` values for the
normal suggestion workflow. `Daily Reviews` needs a `sheet_id` value for the
combined daily run. `Master Reagents` and `Formulations` need IDs when applying
material starter rows. `Experiments`, `Formulations`, and `Results` need IDs
when materializing accepted suggestions into planned follow-up rows, and
`Results` needs an ID when appending normalized Daily Log measurements.

## 3. Validate The Snapshot

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli validate-snapshot \
  --snapshot artifacts/live-sheet-snapshot.json \
  --output artifacts/live-sheet-snapshot-contract-audit.json
```

Fix any missing tabs or header mismatches before running the agent.

## 4. Summarize The Day

Search material roles before scaffolding or reviewing a run when you need to see
which `Master Reagents` rows match the process:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli search-materials \
  --snapshot artifacts/live-sheet-snapshot.json \
  --experiment-id EP-001 \
  --query "particle size latex stability" \
  --output artifacts/live-sheet-material-search-ep-001.json
```

For emulsion polymerization, this expands the process into role groups such as
monomer, initiator, surfactant, and aqueous phase, then reports candidate
reagents, process-knowledge matches, and missing physical-property fields.

Run a per-experiment preflight check when you need to see whether one notebook
entry is ready for planning or result-driven review:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli experiment-preflight \
  --snapshot artifacts/live-sheet-snapshot.json \
  --experiment-id EP-001 \
  --stage review \
  --output artifacts/live-sheet-ep-001-preflight-review.json
```

The report checks required experiment fields, expected material roles,
formulation quantities, Master Reagents physical properties, placeholder
reagents, observations, Results rows, linked literature evidence, and open
suggestions.

Normalize structured Daily Log measurements into appendable `Results` rows when
the operator entered measurements directly in Daily Log columns:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli normalize-daily-log-results \
  --snapshot artifacts/live-sheet-snapshot.json \
  --experiment-id EP-001 \
  --report-output artifacts/live-sheet-daily-log-results.json \
  --batch-output artifacts/live-sheet-daily-log-results-batch.json
```

Audit before applying:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli validate-snapshot \
  --snapshot artifacts/live-sheet-snapshot.json \
  --report artifacts/live-sheet-daily-log-results.json \
  --require-sheet-ids \
  --output artifacts/live-sheet-daily-log-results-audit.json
```

Proceed only if `"valid": true`, then pass
`artifacts/live-sheet-daily-log-results-batch.json` to the Google Sheets
connector batch-update action. Re-capture the sheet before running downstream
daily review commands if this standalone normalization batch was applied.

Generate a read-only daily notebook summary from the captured snapshot:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli daily-summary \
  --snapshot artifacts/live-sheet-snapshot.json \
  --review-date 2026-06-09 \
  --output artifacts/live-sheet-daily-summary.json
```

Review material gaps, measurements, issue tags, and open suggestions before
applying new rows.

To run the daily summary and suggestion agent together, use the combined daily
agent command. It writes pending normalized Results rows, the same read-only
summary, per-experiment preflight checks, role-aware material search, the
appendable agent report, a compact Daily Reviews status row, the pre-apply
audit, and the Google Sheets `batchUpdate` payload from one snapshot:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli daily-agent-run \
  --snapshot artifacts/live-sheet-snapshot.json \
  --review-date 2026-06-09 \
  --litscout-export artifacts/litscout-ep-001.json \
  --run-output artifacts/live-sheet-daily-agent-run.json \
  --summary-output artifacts/live-sheet-daily-summary.json \
  --report-output artifacts/live-sheet-agent-run.json \
  --audit-output artifacts/live-sheet-apply-audit.json \
  --batch-output artifacts/live-sheet-batch-update.json
```

Proceed with the batch output only if `artifacts/live-sheet-apply-audit.json`
has `"valid": true`. The snapshot must include the `Daily Reviews` sheet ID. If
Daily Log measurements normalize into Results, it must also include the
`Results` sheet ID; the batch will append Results rows before Literature
Evidence and Agent Suggestions, then append the Daily Reviews row.

The combined run's `experiment_reviews` block can replace separate
`experiment-preflight` and `search-materials` calls when you want one daily
review artifact for the sheet. Its `daily_log_results_report` block can also
replace the standalone `normalize-daily-log-results` command when you want one
audited batch for the day.

## 5. Scaffold Starter Materials

For a new emulsion-polymerization experiment, generate starter rows for expected
material roles before the run is recorded:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli scaffold-materials \
  --snapshot artifacts/live-sheet-snapshot.json \
  --experiment-id EP-002 \
  --process-type "emulsion polymerization" \
  --report-output artifacts/live-sheet-material-scaffold.json \
  --batch-output artifacts/live-sheet-material-scaffold-batch.json
```

Audit before applying:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli validate-snapshot \
  --snapshot artifacts/live-sheet-snapshot.json \
  --report artifacts/live-sheet-material-scaffold.json \
  --require-sheet-ids \
  --output artifacts/live-sheet-material-scaffold-audit.json
```

Proceed only if `"valid": true`, then pass
`artifacts/live-sheet-material-scaffold-batch.json` to the Google Sheets
connector batch-update action. Replace generated placeholder reagent identities
and physical properties before running the experiment.

## 6. Run The Agent From The Snapshot

Use an existing LitScout export:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli agent-run-snapshot \
  --snapshot artifacts/live-sheet-snapshot.json \
  --review-date 2026-06-09 \
  --litscout-export artifacts/litscout-ep-001.json \
  --report-output artifacts/live-sheet-agent-run.json \
  --batch-output artifacts/live-sheet-batch-update.json
```

The `daily-agent-run` command in step 4 can replace this separate agent run
when a daily summary and an apply-ready suggestion batch are both needed.

Or let the agent run LitScout for experiments that lack evidence:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli agent-run-snapshot \
  --snapshot artifacts/live-sheet-snapshot.json \
  --review-date 2026-06-09 \
  --run-litscout \
  --litscout-limit 8 \
  --evidence-limit 3 \
  --report-output artifacts/live-sheet-agent-run.json \
  --batch-output artifacts/live-sheet-batch-update.json
```

## 7. Audit Before Applying

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli validate-snapshot \
  --snapshot artifacts/live-sheet-snapshot.json \
  --report artifacts/live-sheet-agent-run.json \
  --require-sheet-ids \
  --output artifacts/live-sheet-apply-audit.json
```

Proceed only if `"valid": true`. A report with zero rows to append is a safe
no-op.

## 8. Apply Through Google Sheets

Pass `artifacts/live-sheet-batch-update.json` as the `requests` array to the
Google Sheets connector batch-update action for the live spreadsheet.

After applying, re-capture the same snapshot and rerun steps 3-5. The expected
second-run result is:

```json
{
  "summary": {
    "evidence_rows_to_append": 0,
    "suggestion_rows_to_append": 0,
    "request_count": 0
  }
}
```

## 9. Materialize Accepted Plans

After a human reviews an `Agent Suggestions` row and changes `status` to
`accepted`, recapture the sheet snapshot. Then generate planned `Experiments`,
draft `Formulations`, and expected `Results` rows from the stored
`proposed_plan_json`; the same batch updates the accepted suggestion status to
`run_planned`:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli materialize-accepted-plans \
  --snapshot artifacts/live-sheet-snapshot.json \
  --planned-date 2026-06-10 \
  --report-output artifacts/live-sheet-plan-materialization.json \
  --batch-output artifacts/live-sheet-plan-batch-update.json
```

Audit before applying:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli validate-snapshot \
  --snapshot artifacts/live-sheet-snapshot.json \
  --report artifacts/live-sheet-plan-materialization.json \
  --require-sheet-ids \
  --output artifacts/live-sheet-plan-apply-audit.json
```

Proceed only if `"valid": true`, then pass
`artifacts/live-sheet-plan-batch-update.json` to the Google Sheets connector
batch-update action. A second capture/audit should report zero experiment,
formulation, and result rows to append.
