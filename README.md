# Lab Notebook Agent

This is the first scaffold for a Google Sheets-based daily lab notebook agent.
The workbook is the primary interface: users enter reagents, formulation rows,
observations, results, and literature evidence in consistent tabs. The local CLI
generates that workbook, searches curated process knowledge, and drafts a next
experiment recommendation with copy/paste-ready LitScout commands for literature
evidence.

## Quick Start

```bash
cd /home/bak3r/projects/lab-notebook-agent
PYTHONPATH=src python3 -m lab_notebook_agent.cli init --output artifacts/lab_notebook_template.xlsx
PYTHONPATH=src python3 -m lab_notebook_agent.cli schema --output artifacts/workbook_contract.json
PYTHONPATH=src python3 -m lab_notebook_agent.cli search-notebook --workbook artifacts/lab_notebook_template.xlsx "emulsion polymerization surfactant particle size" --output artifacts/notebook-search-emulsion.json
PYTHONPATH=src python3 -m lab_notebook_agent.cli search-materials --workbook artifacts/lab_notebook_template.xlsx --experiment-id EP-001 --query "particle size latex stability" --output artifacts/material-search-ep-001.json
PYTHONPATH=src python3 -m lab_notebook_agent.cli suggest --entry examples/emulsion_polymerization_entry.json
PYTHONPATH=src python3 -m lab_notebook_agent.cli audit-workbook --workbook artifacts/lab_notebook_template.xlsx --experiment-id EP-001 --output artifacts/ep-001-material-audit.json
PYTHONPATH=src python3 -m lab_notebook_agent.cli experiment-preflight --workbook artifacts/lab_notebook_template.xlsx --experiment-id EP-001 --stage review --output artifacts/ep-001-preflight-review.json
PYTHONPATH=src python3 -m lab_notebook_agent.cli record-experiment --record examples/emulsion_polymerization_record.json --report-output artifacts/record-ep-010.json
PYTHONPATH=src python3 -m lab_notebook_agent.cli record-daily-agent-run --workbook artifacts/lab_notebook_template.xlsx --record examples/emulsion_polymerization_record.json --run-output artifacts/record-daily-agent-ep-010.json
PYTHONPATH=src python3 -m lab_notebook_agent.cli normalize-formulations --workbook artifacts/lab_notebook_template.xlsx --experiment-id EP-001 --report-output artifacts/formulation-normalization-ep-001.json
PYTHONPATH=src python3 -m lab_notebook_agent.cli normalize-daily-log-results --workbook artifacts/lab_notebook_template.xlsx --experiment-id EP-001 --report-output artifacts/daily-log-results-ep-001.json
PYTHONPATH=src python3 -m lab_notebook_agent.cli daily-summary --workbook artifacts/lab_notebook_template.xlsx --review-date 2026-06-09 --output artifacts/daily-summary-2026-06-09.json
PYTHONPATH=src python3 -m lab_notebook_agent.cli daily-agent-run --workbook artifacts/lab_notebook_template.xlsx --review-date 2026-06-09 --litscout-export artifacts/litscout-ep-001.json --run-output artifacts/daily-agent-run-2026-06-09.json
PYTHONPATH=src python3 -m lab_notebook_agent.cli scaffold-materials --workbook artifacts/lab_notebook_template.xlsx --experiment-id EP-002 --process-type "emulsion polymerization" --report-output artifacts/material-scaffold-ep-002.json
PYTHONPATH=src python3 -m lab_notebook_agent.cli entry-from-workbook --workbook artifacts/lab_notebook_template.xlsx --experiment-id EP-001 --output artifacts/ep-001-entry.json
PYTHONPATH=src python3 -m lab_notebook_agent.cli suggest-workbook --workbook artifacts/lab_notebook_template.xlsx --experiment-id EP-001 --output artifacts/ep-001-suggestion.json
PYTHONPATH=src python3 -m lab_notebook_agent.cli agent-run --workbook artifacts/lab_notebook_template.xlsx --experiment-id EP-001 --litscout-export artifacts/litscout-ep-001.json --report-output artifacts/agent-run-ep-001.json
PYTHONPATH=src python3 -m lab_notebook_agent.cli agent-run --workbook artifacts/lab_notebook_template.xlsx --review-date 2026-06-09 --litscout-export artifacts/litscout-ep-001.json --report-output artifacts/daily-review-2026-06-09.json
PYTHONPATH=src python3 -m lab_notebook_agent.cli snapshot-from-workbook --workbook artifacts/lab_notebook_agent_applied.xlsx --sheet-id "Literature Evidence=1198739748" --sheet-id "Agent Suggestions=89758567" --output artifacts/live-sheet-snapshot-proxy.json
PYTHONPATH=src python3 -m lab_notebook_agent.cli google-capture-plan --spreadsheet-id 1swzNI5YXruBwl0KgoG3b0hrmD12GopLf71YfKHs4AM8 --output artifacts/google-capture-plan.json
PYTHONPATH=src python3 -m unittest discover -s tests
```

The generated `artifacts/lab_notebook_template.xlsx` can be imported into Google
Sheets. The tab names and headers are the working contract for future connector
automation.

## Workbook Tabs

- `Master Reagents`: canonical inventory and physical properties such as role,
  molecular weight, density, supplier, lot, hazards, and notes.
- `Experiments`: one row per planned or completed experiment.
- `Daily Log`: timestamped observations from the run.
- `Formulations`: reagent amounts, phases, roles, feed timing, and notes.
- `Results`: measurements and interpretations.
- `Literature Evidence`: rows exported or summarized from LitScout.
- `Agent Suggestions`: recommendations the agent proposes back to the user,
  including structured proposed-plan JSON for accepted follow-ups.
- `Daily Reviews`: one compact status row per daily agent run.
- `Process Knowledge`: compact process priors used for semantic lookup.
- `Controlled Vocab`: dropdown values shared by tabs, including process types,
  reagent categories, formulation roles, process stages, result quality flags,
  suggestion statuses, and daily review statuses.
- `Agent Config`: model, retrieval, and safety settings.

## LitScout Bridge

The recommendation output includes reproducible commands for a manual LitScout
round-trip:

```bash
litscout search multi "emulsion polymerization particle size surfactant initiator" --sources openalex,crossref,semantic_scholar --depth light --limit 25 --save --session-name labnotebook/ep-001
litscout sessions export labnotebook/ep-001 --format json --json-array --output artifacts/litscout-ep-001.json
```

Those exported works are intended to populate `Literature Evidence`, then feed
back into `Agent Suggestions`.

Convert an exported LitScout session into rows for the `Literature Evidence`
tab:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli evidence-from-litscout \
  --input artifacts/litscout-ep-001.json \
  --experiment-id EP-001 \
  --query "emulsion polymerization surfactant particle size coagulum latex stability" \
  --limit 3 \
  --values \
  --output artifacts/literature-evidence-ep-001-values.json
```

Run the workbook-backed agent in dry-run mode:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli agent-run \
  --workbook artifacts/lab_notebook_template.xlsx \
  --experiment-id EP-001 \
  --litscout-export artifacts/litscout-ep-001.json \
  --report-output artifacts/agent-run-ep-001.json
```

When the `litscout` CLI is available, the agent can run the search/export step
itself for experiments that do not already have `Literature Evidence` rows:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli agent-run \
  --workbook artifacts/lab_notebook_template.xlsx \
  --experiment-id EP-001 \
  --run-litscout \
  --litscout-limit 8 \
  --evidence-limit 3 \
  --report-output artifacts/agent-run-ep-001-live-litscout.json
```

Each run records `litscout_status`. If the LitScout CLI is missing or returns a
non-zero status, the report marks that experiment `skipped` with
`skip_reason: litscout_failed` and does not append an ungrounded suggestion.
When evidence rows are present, the recommendation also includes a
`literature_context` block with evidence IDs, relevance tag counts, concise
findings, and guidance inferred from tags or finding text.
Agent runs also include `historical_context` for same-process prior experiments,
including result benchmarks and guidance when previous runs reached better
particle size, conversion, or coagulum outcomes.

Run the same agent as a daily notebook review. This processes experiments whose
`Experiments.date` or `Daily Log.timestamp` starts with the requested date, and
records the selected IDs in the report:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli daily-summary \
  --workbook artifacts/lab_notebook_template.xlsx \
  --review-date 2026-06-09 \
  --output artifacts/daily-summary-2026-06-09.json
```

The summary reports observations, normalized Results rows, issue tags, material
audit status, open suggestions, and next actions for each experiment selected on
that date.

Before running or reviewing one experiment, use `experiment-preflight` to check
the notebook rows that the agent depends on:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli experiment-preflight \
  --workbook artifacts/lab_notebook_template.xlsx \
  --experiment-id EP-001 \
  --stage review \
  --output artifacts/ep-001-preflight-review.json
```

The preflight report checks required `Experiments` fields, emulsion
polymerization roles, formulation quantities, Master Reagents physical
properties, generated placeholder reagents, Daily Log observations, Results
measurements, linked literature evidence, and open suggestions. Use
`--stage planning` before a run and `--stage review` when the agent should make
a result-driven follow-up suggestion.

Use `record-experiment` to turn a structured run record into appendable
`Experiments`, `Formulations`, `Daily Log`, and `Results` rows:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli record-experiment \
  --record examples/emulsion_polymerization_record.json \
  --report-output artifacts/record-ep-010.json
```

Apply the generated rows to a workbook copy:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli record-experiment \
  --record examples/emulsion_polymerization_record.json \
  --workbook artifacts/lab_notebook_template.xlsx \
  --apply \
  --workbook-output artifacts/lab_notebook_recorded.xlsx \
  --report-output artifacts/record-ep-010-applied.json
```

For a Google Sheets snapshot, include sheet IDs for `Experiments`,
`Formulations`, `Daily Log`, and `Results`, then emit an audited batch:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli record-experiment \
  --record examples/emulsion_polymerization_record.json \
  --snapshot artifacts/live-sheet-snapshot.json \
  --report-output artifacts/live-sheet-record-ep-010.json \
  --audit-output artifacts/live-sheet-record-ep-010-audit.json \
  --batch-output artifacts/live-sheet-record-ep-010-batch.json
```

Use `record-daily-agent-run` when you want one report that first projects the
structured record into the notebook, then runs the daily agent from that
projected state. The combined snapshot batch appends the record rows, pending
normalized Results, Literature Evidence, Agent Suggestions, and the Daily
Reviews row in one auditable payload:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli record-daily-agent-run \
  --workbook artifacts/lab_notebook_template.xlsx \
  --record examples/emulsion_polymerization_record.json \
  --litscout-export artifacts/litscout-ep-010.json \
  --apply \
  --workbook-output artifacts/lab_notebook_recorded_daily.xlsx \
  --run-output artifacts/record-daily-agent-ep-010-applied.json
```

Use `--litscout-export` with a reviewed LitScout JSON export, or
`--run-litscout` when the local LitScout CLI is available, so the newly recorded
experiment gets `Literature Evidence` rows before the follow-up suggestion is
generated. The resulting `Agent Suggestions` row links those evidence IDs for
human review.

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

Use `normalize-formulations` after entering at least one quantitative basis in
`Formulations` and the matching physical properties in `Master Reagents`. It
fills blank `mass_g`, `volume_mL`, and `moles_mmol` cells when those values can
be derived from existing mass, volume, moles, molecular weight, or density. It
skips populated cells, so the command can be rerun safely:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli normalize-formulations \
  --workbook artifacts/lab_notebook_template.xlsx \
  --experiment-id EP-001 \
  --report-output artifacts/formulation-normalization-ep-001.json
```

Apply generated formulation cells to a workbook copy:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli normalize-formulations \
  --workbook artifacts/lab_notebook_template.xlsx \
  --experiment-id EP-001 \
  --apply \
  --workbook-output artifacts/lab_notebook_formulation_normalized.xlsx \
  --report-output artifacts/formulation-normalization-ep-001-applied.json
```

For a Google Sheets snapshot with the `Formulations` sheet ID captured, emit an
auditable `batchUpdate` payload instead:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli normalize-formulations \
  --snapshot artifacts/live-sheet-snapshot.json \
  --experiment-id EP-001 \
  --report-output artifacts/live-sheet-formulation-normalization.json \
  --batch-output artifacts/live-sheet-formulation-normalization-batch.json
```

Use `normalize-daily-log-results` to turn structured Daily Log measurements and
common free-text phrases into normalized `Results` rows. It recognizes entries
such as temperature, rpm, pH, solids, particle size, conversion, viscosity, and
coagulum mass. Existing matching Results values are skipped so the operation can
be rerun safely:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli normalize-daily-log-results \
  --workbook artifacts/lab_notebook_template.xlsx \
  --experiment-id EP-001 \
  --report-output artifacts/daily-log-results-ep-001.json
```

Apply normalized rows to a workbook copy:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli normalize-daily-log-results \
  --workbook artifacts/lab_notebook_template.xlsx \
  --experiment-id EP-001 \
  --apply \
  --workbook-output artifacts/lab_notebook_daily_log_results.xlsx \
  --report-output artifacts/daily-log-results-ep-001-applied.json
```

Run the combined daily notebook agent when you want pending normalized Results
rows, the summary, per-experiment preflight checks, role-aware material search,
literature evidence rows, suggestion rows, a compact `Daily Reviews` row, and
`Experiments` status/next-step/summary updates from one command:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli daily-agent-run \
  --workbook artifacts/lab_notebook_template.xlsx \
  --review-date 2026-06-09 \
  --litscout-export artifacts/litscout-ep-001.json \
  --run-output artifacts/daily-agent-run-2026-06-09.json \
  --summary-output artifacts/daily-agent-summary-2026-06-09.json \
  --report-output artifacts/daily-agent-report-2026-06-09.json
```

For a Google Sheets snapshot with target sheet IDs, the same command includes a
pre-apply audit and emits `batchUpdate` requests only when that audit is valid.
The daily snapshot must include the `Experiments` and `Daily Reviews` sheet IDs.
When Daily Log measurements normalize into Results, it must also include the
`Results` sheet ID in addition to `Literature Evidence` and
`Agent Suggestions`:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli daily-agent-run \
  --snapshot artifacts/live-sheet-snapshot.json \
  --review-date 2026-06-09 \
  --litscout-export artifacts/litscout-ep-001.json \
  --run-output artifacts/live-sheet-daily-agent-run.json \
  --audit-output artifacts/live-sheet-daily-agent-audit.json \
  --batch-output artifacts/live-sheet-daily-agent-batch.json
```

The combined run includes an `experiment_reviews` block for each selected
experiment. Each review embeds the same `experiment-preflight` and
`search-materials` reports so the daily run can show both the result-driven next
experiment suggestion and the notebook/material gaps that would make that
suggestion hard to execute. It also includes `daily_log_results_report`, and the
snapshot batch appends those normalized Results rows before literature evidence
and agent suggestions, then appends the compact Daily Reviews status row and
updates the selected Experiments row.

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli agent-run \
  --workbook artifacts/lab_notebook_template.xlsx \
  --review-date 2026-06-09 \
  --litscout-export artifacts/litscout-ep-001.json \
  --report-output artifacts/daily-review-2026-06-09.json
```

The same `--review-date YYYY-MM-DD` filter is available for
`agent-run-snapshot` and `google-agent-run-live`.

Agent run reports also include `notebook_context_matches`: notebook-wide search
hits related to the run query, excluding the current experiment's own
experiment/log/formulation/result rows where possible. Tune with
`--context-limit`; use `--context-limit 0` to disable this context block. Same
process prior-result memory is controlled separately with `--history-limit`;
use `--history-limit 0` when the suggestion should ignore prior experiment
benchmarks.

Apply that run to a workbook copy:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli agent-run \
  --workbook artifacts/lab_notebook_template.xlsx \
  --experiment-id EP-001 \
  --litscout-export artifacts/litscout-ep-001.json \
  --apply \
  --workbook-output artifacts/lab_notebook_agent_applied.xlsx \
  --report-output artifacts/agent-run-ep-001-applied.json
```

Emit raw Google Sheets `batchUpdate` requests from the same report:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli google-batch-from-report \
  --report artifacts/agent-run-ep-001.json \
  --literature-evidence-sheet-id 1198739748 \
  --agent-suggestions-sheet-id 89758567 \
  --output artifacts/google-batch-ep-001.json
```

See [docs/live-google-sheets-workflow.md](docs/live-google-sheets-workflow.md)
for the re-authenticated Google Sheets connector capture, audit, and apply
workflow.

## Notebook Search

`search-knowledge` searches the bundled process-knowledge records.
`search-notebook` searches the actual notebook rows from a workbook or Google
Sheets snapshot, including Master Reagents, Experiments, Daily Log,
Formulations, Results, Literature Evidence, Agent Suggestions, Daily Reviews,
and Process Knowledge.

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli search-notebook \
  --workbook artifacts/lab_notebook_template.xlsx \
  "emulsion polymerization surfactant particle size" \
  --output artifacts/notebook-search-emulsion.json
```

Restrict to specific tabs with repeatable `--sheet` flags:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli search-notebook \
  --snapshot artifacts/live-sheet-snapshot.json \
  --sheet "Daily Log" \
  "coagulum stir shaft particle size"
```

Use `search-materials` when the question is role-aware rather than a generic
row search. For emulsion polymerization, the report expands the process into
expected role groups such as monomer, initiator, surfactant, and aqueous phase,
then searches `Master Reagents` and `Process Knowledge` for candidates and
property gaps:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli search-materials \
  --workbook artifacts/lab_notebook_template.xlsx \
  --experiment-id EP-001 \
  --query "particle size latex stability" \
  --output artifacts/material-search-ep-001.json
```

Add `--include-optional` to include optional crosslinker or chain-transfer
roles. The same command accepts `--snapshot artifacts/live-sheet-snapshot.json`
for Google Sheets captures.

## Material Starter Rows

For a new experiment, the agent can scaffold process-aware starter rows before
the run is recorded. For emulsion polymerization, it checks expected roles such
as monomer, initiator, surfactant, and aqueous phase. Existing `Master Reagents`
rows are reused when possible; otherwise the report creates placeholder reagent
rows that must be replaced with verified identities and properties.

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli scaffold-materials \
  --workbook artifacts/lab_notebook_template.xlsx \
  --experiment-id EP-002 \
  --process-type "emulsion polymerization" \
  --report-output artifacts/material-scaffold-ep-002.json
```

Apply the starter rows to a workbook copy:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli scaffold-materials \
  --workbook artifacts/lab_notebook_template.xlsx \
  --experiment-id EP-002 \
  --process-type "emulsion polymerization" \
  --apply \
  --workbook-output artifacts/lab_notebook_material_scaffolded.xlsx \
  --report-output artifacts/material-scaffold-ep-002-applied.json
```

For a Google Sheets snapshot, the same report can emit `batchUpdate` requests
for `Master Reagents` and `Formulations` when those sheet IDs are present:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli scaffold-materials \
  --snapshot artifacts/live-sheet-snapshot.json \
  --experiment-id EP-002 \
  --process-type "emulsion polymerization" \
  --report-output artifacts/live-sheet-material-scaffold.json \
  --batch-output artifacts/live-sheet-material-scaffold-batch.json
```

The same workflow can run directly against the Google Sheets API when local
credentials are available:

```bash
pip install -e .[google]

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
  --litscout-export artifacts/litscout-ep-001.json \
  --snapshot-output artifacts/live-google-snapshot.json \
  --report-output artifacts/live-google-agent-run.json \
  --audit-output artifacts/live-google-agent-audit.json \
  --batch-output artifacts/live-google-agent-batch.json
```

Normalize formulation quantity cells directly against the live sheet with the
same capture, audit, and optional apply flow:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli google-normalize-formulations-live \
  --spreadsheet-id 1swzNI5YXruBwl0KgoG3b0hrmD12GopLf71YfKHs4AM8 \
  --experiment-id EP-001 \
  --snapshot-output artifacts/live-google-formulation-snapshot.json \
  --report-output artifacts/live-google-formulation-normalization.json \
  --audit-output artifacts/live-google-formulation-audit.json \
  --batch-output artifacts/live-google-formulation-batch.json
```

Normalize Daily Log measurements directly against the live sheet when you want
to append pending `Results` before running the daily agent:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli google-normalize-daily-log-results-live \
  --spreadsheet-id 1swzNI5YXruBwl0KgoG3b0hrmD12GopLf71YfKHs4AM8 \
  --review-date 2026-06-09 \
  --snapshot-output artifacts/live-google-daily-log-snapshot.json \
  --report-output artifacts/live-google-daily-log-results.json \
  --audit-output artifacts/live-google-daily-log-audit.json \
  --batch-output artifacts/live-google-daily-log-batch.json
```

For a one-command daily review against the live sheet, use the daily live
runner:

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

Add `--apply` only after the audit is valid. By default the direct API path uses
Application Default Credentials; pass `--service-account-file path/to/key.json`
for a service account that has edit access to the spreadsheet.

On Debian-managed Python environments where `pip install --user` is blocked and
`python3-venv` is unavailable, install the optional dependencies into an ignored
local target directory:

```bash
python3 -m pip install --target .python-deps/google google-auth requests
PYTHONPATH=.python-deps/google:src python3 -m lab_notebook_agent.cli google-doctor \
  --spreadsheet-id 1swzNI5YXruBwl0KgoG3b0hrmD12GopLf71YfKHs4AM8
```

## Next Experiment Plan

Recommendation JSON includes both the appendable `Agent Suggestions` row fields
and a structured `proposed_experiment_plan`. The plan keeps the recommendation
reviewable before execution:

- `parent_experiment_id` and `suggested_experiment_id` for traceability.
- objective, hypothesis, variables, controls, prerequisites, and acceptance
  criteria for the proposed follow-up.
- linked `Literature Evidence` IDs used to support the draft.
- `result_support` with target comparisons, limiting metrics, and guidance from
  the current Results and structured Daily Log measurements.
- `literature_support` with the evidence tags, guidance, and findings that
  influenced the recommendation.
- `history_support` with same-process prior experiments, result benchmarks, and
  notebook-history guidance used as controls or comparison points.
- `sheet_rows` with draft `Experiments` values, copied/reviewable
  `Formulations` rows, and expected `Results` measurements to capture.

For emulsion polymerization entries, the plan isolates particle-size,
coagulum/stability, and conversion signals into controlled follow-up variables
such as surfactant package, surfactant active basis, monomer feed duration, and
initiator/process-health checks. Quantitative changes stay gated by the material
audit until reagent roles, masses, volumes, molecular weights, and densities are
complete enough for a defensible formulation.

After a human reviews a suggestion, set its `status` to `accepted` in
`Agent Suggestions`. The materializer turns accepted suggestions into concrete
notebook rows for `Experiments`, `Formulations`, and `Results`, then updates
the original suggestion status to `run_planned`:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli materialize-accepted-plans \
  --workbook artifacts/lab_notebook_agent_applied.xlsx \
  --planned-date 2026-06-10 \
  --apply \
  --workbook-output artifacts/lab_notebook_agent_planned.xlsx \
  --report-output artifacts/accepted-plan-materialization.json
```

For a Google Sheets snapshot, the same command can emit `batchUpdate` requests
for `Experiments`, `Formulations`, `Results`, and the
`Agent Suggestions.status` update when the snapshot includes those sheet IDs:

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli materialize-accepted-plans \
  --snapshot artifacts/live-sheet-snapshot.json \
  --planned-date 2026-06-10 \
  --report-output artifacts/live-sheet-plan-materialization.json \
  --batch-output artifacts/live-sheet-plan-batch-update.json
```

## Material Audit

The agent has a process-aware material audit before it treats a recommendation
as quantitatively ready. For emulsion polymerization it checks whether the
formulation includes the expected roles:

- monomer or comonomer
- initiator
- surfactant
- optional aqueous phase, buffer, crosslinker, or chain-transfer agent

It also flags formulation rows that lack a quantitative basis (`mass_g`,
`volume_mL`, `moles_mmol`, `wt_percent`, or `concentration`) and Master
Reagents fields needed for calculations such as molecular weight and density.
Where possible, the audit derives formulation values:

- `moles_mmol` from `mass_g` and `molecular_weight_g_mol`
- `mass_g` from `volume_mL` and `density_g_mL`
- `volume_mL` from `mass_g` and `density_g_mL`
- `mass_g` from `moles_mmol` and `molecular_weight_g_mol`

The read-only audit reports these calculations. The `normalize-formulations`
command uses the same calculation rules to write only blank formulation quantity
cells, leaving operator-entered values untouched.

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli audit-workbook \
  --workbook artifacts/lab_notebook_template.xlsx \
  --experiment-id EP-001 \
  --output artifacts/ep-001-material-audit.json
```

## Current Scope

This scaffold builds the workbook contract, local recommendation loop, LitScout
handoff/retrieval path, idempotent workbook runner, accepted-plan
materialization, material starter rows, experiment preflight checks, combined
daily review, Daily Log to Results normalization, formulation quantity
normalization, role-aware material search, and Google Sheets snapshot runner. It
does not yet watch a live spreadsheet continuously.
