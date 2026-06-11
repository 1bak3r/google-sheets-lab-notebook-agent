# Live Google Sheets Workflow

This runbook connects the local lab notebook agent to a Google Sheet without
changing the core agent logic.

## Current Live Sheet

- Spreadsheet ID: `1swzNI5YXruBwl0KgoG3b0hrmD12GopLf71YfKHs4AM8`
- URL: `https://docs.google.com/spreadsheets/d/1swzNI5YXruBwl0KgoG3b0hrmD12GopLf71YfKHs4AM8`
- Append target sheet IDs:
  - `Master Reagents`: recapture from spreadsheet metadata before applying starter rows
  - `Formulations`: recapture from spreadsheet metadata before applying starter rows, formulation normalization, or accepted plans
  - `Daily Log`: recapture from spreadsheet metadata before applying structured experiment records
  - `Literature Evidence`: `1198739748`
  - `Agent Suggestions`: `89758567`
  - `Experiments`: recapture from spreadsheet metadata before applying daily reviews or accepted plans
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

## 1. Setup Or Repair Contract Tabs

Use the direct Google API setup command before snapshot capture when the live
spreadsheet may be blank, partially imported, or missing dropdowns. The setup
batch creates missing contract tabs, writes header rows, freezes row 1, formats
headers, autosizes columns, and adds controlled-vocabulary dropdowns through row
1000. It does not seed example data into a live sheet.

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli google-doctor \
  --spreadsheet-id 1swzNI5YXruBwl0KgoG3b0hrmD12GopLf71YfKHs4AM8 \
  --output artifacts/google-doctor.json

PYTHONPATH=src python3 -m lab_notebook_agent.cli google-setup-live \
  --spreadsheet-id 1swzNI5YXruBwl0KgoG3b0hrmD12GopLf71YfKHs4AM8 \
  --audit-output artifacts/google-setup-audit.json \
  --batch-output artifacts/google-setup-batch.json \
  --run-output artifacts/google-setup-run.json
```

Review the audit and batch first. Add `--apply` to the same
`google-setup-live` command only after confirming the Google credentials have
edit access to the spreadsheet.

## 2. Generate The Capture Plan

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

PYTHONPATH=src python3 -m lab_notebook_agent.cli google-setup-live \
  --spreadsheet-id 1swzNI5YXruBwl0KgoG3b0hrmD12GopLf71YfKHs4AM8 \
  --audit-output artifacts/live-google-setup-audit.json \
  --batch-output artifacts/live-google-setup-batch.json

PYTHONPATH=src python3 -m lab_notebook_agent.cli google-record-experiment-live \
  --spreadsheet-id 1swzNI5YXruBwl0KgoG3b0hrmD12GopLf71YfKHs4AM8 \
  --record examples/emulsion_polymerization_record.json \
  --snapshot-output artifacts/live-google-record-snapshot.json \
  --report-output artifacts/live-google-record-ep-010.json \
  --audit-output artifacts/live-google-record-ep-010-audit.json \
  --batch-output artifacts/live-google-record-ep-010-batch.json

PYTHONPATH=src python3 -m lab_notebook_agent.cli google-record-daily-agent-run-live \
  --spreadsheet-id 1swzNI5YXruBwl0KgoG3b0hrmD12GopLf71YfKHs4AM8 \
  --record examples/emulsion_polymerization_record.json \
  --litscout-export artifacts/litscout-ep-010.json \
  --snapshot-output artifacts/live-google-record-daily-snapshot.json \
  --record-output artifacts/live-google-record-ep-010.json \
  --daily-run-output artifacts/live-google-record-daily-agent-ep-010.json \
  --audit-output artifacts/live-google-record-daily-ep-010-audit.json \
  --batch-output artifacts/live-google-record-daily-ep-010-batch.json

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

Formulation quantity normalization can also run directly against the live sheet:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli google-normalize-formulations-live \
  --spreadsheet-id 1swzNI5YXruBwl0KgoG3b0hrmD12GopLf71YfKHs4AM8 \
  --experiment-id EP-001 \
  --snapshot-output artifacts/live-google-formulation-snapshot.json \
  --report-output artifacts/live-google-formulation-normalization.json \
  --audit-output artifacts/live-google-formulation-audit.json \
  --batch-output artifacts/live-google-formulation-batch.json
```

Daily Log measurement normalization has the same direct live path:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli google-normalize-daily-log-results-live \
  --spreadsheet-id 1swzNI5YXruBwl0KgoG3b0hrmD12GopLf71YfKHs4AM8 \
  --review-date 2026-06-09 \
  --snapshot-output artifacts/live-google-daily-log-snapshot.json \
  --report-output artifacts/live-google-daily-log-results.json \
  --audit-output artifacts/live-google-daily-log-audit.json \
  --batch-output artifacts/live-google-daily-log-batch.json
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

## 3. Capture A Snapshot

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

`Experiments`, `Literature Evidence`, and `Agent Suggestions` need `sheet_id`
values for the normal suggestion workflow, because linked evidence IDs are also
written back to the parent experiment row. `Daily Reviews` needs a `sheet_id`
value for the combined daily run. `Master Reagents` and `Formulations` need IDs
when applying material starter rows, and `Formulations` needs an ID when writing
normalized formulation quantity cells. `Experiments`, `Formulations`,
`Daily Log`, and `Results` need IDs when applying a structured experiment
record. `Experiments`, `Formulations`, and `Results` need IDs when
materializing accepted suggestions into planned follow-up rows, and `Results`
needs an ID when appending normalized Daily Log measurements.

## 4. Validate The Snapshot

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli validate-snapshot \
  --snapshot artifacts/live-sheet-snapshot.json \
  --output artifacts/live-sheet-snapshot-contract-audit.json
```

Fix any missing tabs or header mismatches before running the agent.

## 5. Summarize The Day

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
The `scaffold-materials` command uses the same ranked candidate signal when it
creates starter formulation rows. Add `--query` to bias selection toward the
planned chemistry or issue being investigated; semantic-only matches are
reported by search but are not auto-selected for starter rows without a
matching role/category.

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

Convert a structured experiment record JSON into appendable notebook rows when
the operator has captured a run outside the sheet or in an intake form:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli record-experiment \
  --record examples/emulsion_polymerization_record.json \
  --snapshot artifacts/live-sheet-snapshot.json \
  --report-output artifacts/live-sheet-record-ep-010.json \
  --audit-output artifacts/live-sheet-record-ep-010-audit.json \
  --batch-output artifacts/live-sheet-record-ep-010-batch.json
```

The record may include top-level `master_reagents` or `reagents`, nested
`formulation[].reagent` objects, or prefixed formulation fields such as
`reagent_density_g_mL` and `reagent_supplier`. When the snapshot includes
`Master Reagents`, the batch appends new reagent rows and fills blank cells on
existing rows by `reagent_id`; conflicting nonblank values are returned as
warnings and are not overwritten. The same batch appends `Experiments`,
`Formulations`, `Daily Log`, and `Results` rows. Proceed only if the audit is
valid; otherwise fix duplicate experiment IDs, duplicate Daily Log
timestamps/observations, or missing sheet IDs before applying.

Use the combined record-plus-daily command when a newly captured record should
immediately drive normalized Results, LitScout-backed evidence, an Agent
Suggestions row, a Daily Reviews row, and experiment status/summary updates:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli record-daily-agent-run \
  --snapshot artifacts/live-sheet-snapshot.json \
  --record examples/emulsion_polymerization_record.json \
  --litscout-export artifacts/litscout-ep-010.json \
  --run-output artifacts/live-sheet-record-daily-ep-010.json \
  --record-output artifacts/live-sheet-record-ep-010.json \
  --daily-run-output artifacts/live-sheet-record-daily-agent-ep-010.json \
  --audit-output artifacts/live-sheet-record-daily-ep-010-audit.json \
  --batch-output artifacts/live-sheet-record-daily-ep-010-batch.json
```

The command runs the daily agent against a projected notebook that includes the
new record, then emits one batch for the original sheet. Updates for the newly
appended experiment are folded into that appended `Experiments` row so the batch
does not depend on updating a row that does not exist yet.

Normalize blank formulation quantity cells when the sheet already has enough
inputs to calculate them. The command derives missing `mass_g`, `volume_mL`, or
`moles_mmol` values from existing formulation quantities plus `Master Reagents`
molecular weight and density fields:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli normalize-formulations \
  --snapshot artifacts/live-sheet-snapshot.json \
  --experiment-id EP-001 \
  --report-output artifacts/live-sheet-formulation-normalization.json \
  --batch-output artifacts/live-sheet-formulation-normalization-batch.json
```

Audit before applying:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli validate-snapshot \
  --snapshot artifacts/live-sheet-snapshot.json \
  --report artifacts/live-sheet-formulation-normalization.json \
  --require-sheet-ids \
  --output artifacts/live-sheet-formulation-normalization-audit.json
```

Proceed only if `"valid": true`, then pass
`artifacts/live-sheet-formulation-normalization-batch.json` to the Google Sheets
connector batch-update action. Re-capture the sheet before downstream preflight
or daily review commands if the normalization batch was applied. If local
Google API credentials are available, the
`google-normalize-formulations-live` command in the direct API section performs
the capture, report, audit, and optional apply in one command.

Normalize structured Daily Log measurements and common free-text measurement
phrases into appendable `Results` rows when the operator entered measurements
directly in Daily Log:

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
daily review commands if this standalone normalization batch was applied. If
local Google API credentials are available, the
`google-normalize-daily-log-results-live` command in the direct API section
performs the capture, report, audit, and optional apply in one command.

Generate a read-only daily notebook summary from the captured snapshot:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli daily-summary \
  --snapshot artifacts/live-sheet-snapshot.json \
  --review-date 2026-06-09 \
  --output artifacts/live-sheet-daily-summary.json
```

Review material gaps, measurements, target-based result-analysis summaries,
limiting metrics, issue tags, and open suggestions before applying new rows.
Open-suggestion next actions are status-aware: draft suggestions should be
accepted or rejected, accepted suggestions should be materialized, and completed
planned follow-ups should be marked `run_complete`. The combined daily agent
apply/batch path emits that `run_complete` status update automatically when the
suggestion is `run_planned` and its proposed follow-up experiment is `complete`.

To run the daily summary and suggestion agent together, use the combined daily
agent command. It writes pending normalized Results rows, the same read-only
summary, per-experiment preflight checks, role-aware material search, the
appendable agent report, a compact Daily Reviews status row, Experiments
status/next-step/summary updates, the pre-apply audit, and the Google Sheets
`batchUpdate` payload from one snapshot:

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

Use `--history-limit N` on `daily-agent-run`, `agent-run-snapshot`, and the
live Google agent commands to control how many same-process prior experiments
are used as result benchmarks. Use `--history-limit 0` to disable this notebook
memory block for a run.

Proceed with the batch output only if `artifacts/live-sheet-apply-audit.json`
has `"valid": true`. The snapshot must include the `Experiments` and
`Daily Reviews` sheet IDs. If Daily Log measurements normalize into Results, it
must also include the `Results` sheet ID; the batch will append Results rows
before Literature Evidence and Agent Suggestions, append the Daily Reviews row,
then update the selected Experiments row.

The combined run's `experiment_reviews` block can replace separate
`experiment-preflight` and `search-materials` calls when you want one daily
review artifact for the sheet. The Daily Reviews next-actions JSON also carries
the first result-limit guidance for experiments with out-of-target measurements.
Its `daily_log_results_report` block can also replace the standalone
`normalize-daily-log-results` command when you want one audited batch for the
day.

## 6. Scaffold Starter Materials

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

## 7. Run The Agent From The Snapshot

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

The report records `litscout_status` for each experiment. If the LitScout CLI is
missing or a search/export command fails, that experiment is marked `skipped`
with `skip_reason: litscout_failed`, and no Literature Evidence or Agent
Suggestions rows are emitted for it.
Existing reviewed evidence is reused when a `Literature Evidence.evidence_id`
uses the generated `LIT-{experiment_id}-...` prefix or when that evidence ID is
listed in `Experiments.linked_literature_ids`.
When evidence is available, each suggestion includes `literature_context`, and
the proposed plan includes `literature_support` so reviewers can see which tags
and findings influenced the follow-up.
Each suggestion also includes `result_analysis`, and the proposed plan includes
`result_support`, so target comparisons and limiting metrics are explicit.
Agent runs also include `historical_context`, and proposed plans include
`history_support`, so same-process prior Results rows can be used as controls
or benchmarks when reviewing the next experiment.
Follow-up experiment IDs are allocated from the live sheet snapshot: if a parent
experiment already has `EP-001-FUP-001` in `Experiments` or prior
`Agent Suggestions`, the next draft uses `EP-001-FUP-002` to avoid
materialization collisions.

## 8. Audit Before Applying

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli validate-snapshot \
  --snapshot artifacts/live-sheet-snapshot.json \
  --report artifacts/live-sheet-agent-run.json \
  --require-sheet-ids \
  --output artifacts/live-sheet-apply-audit.json
```

Proceed only if `"valid": true`. A report with zero rows to append is a safe
no-op.

## 9. Apply Through Google Sheets

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

## 10. Materialize Accepted Plans

After a human reviews an `Agent Suggestions` row and changes `status` to
`accepted`, recapture the sheet snapshot. Then generate planned `Experiments`,
draft `Formulations`, and expected `Results` rows from the stored
`proposed_plan_json`; the same batch updates the accepted suggestion status to
`run_planned`:

Agent reruns treat `draft`, `accepted`, and `run_planned` as active suggestion
statuses. Set completed follow-ups to `run_complete`, or declined suggestions to
`rejected`, before asking the agent for a fresh recommendation on that
experiment. The daily agent emits the `run_complete` update automatically when a
planned follow-up experiment reaches `complete`.

For emulsion-polymerization suggestions, the stored plan may include
`planned_formulation_adjustments`. These are conservative row-level changes
derived from result/literature signals, such as a +15% surfactant basis when a
numeric surfactant row exists, or a slower monomer feed when particle size is
high and no numeric surfactant basis is available. The materialized
`Formulations` rows include the proposed value plus notes for human review
before execution.

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
