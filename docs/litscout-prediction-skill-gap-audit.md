# LitScout Prediction Skill Gap Audit

Date: 2026-06-16

Purpose: verify that the lab notebook scaffold can use LitScout evidence to
predict a next experiment, and make the remaining lab-notebook skill gaps
explicit before a human treats the recommendation as executable.

## Verification Command

```bash
PYTHONPATH=src python3 -m lab_notebook_agent.cli predict-next-experiment \
  --workbook artifacts/lab_notebook_template.xlsx \
  --experiment-id EP-001 \
  --run-litscout \
  --litscout-limit 5 \
  --evidence-limit 3 \
  --force \
  --output artifacts/litscout-prediction-ep-001-live.json
```

Live LitScout execution succeeded. The command saved records into the
`labnotebook/ep-001` LitScout session, exported 18 works to
`artifacts/litscout-ep-001.json`, and wrote the prediction report to
`artifacts/litscout-prediction-ep-001-live.json`.

## Prediction Result

The report now generates the prediction payload but keeps the report status
`blocked` until safety review is recorded. This is intentional: the agent can
propose a next experiment, but the notebook should not treat that prediction as
accepted until the safety gate is complete.

The predicted follow-up is `EP-001-FUP-001`, a controlled emulsion
polymerization follow-up that keeps monomer identity, target solids,
temperature, agitation, and total initiator basis fixed while isolating
latex-stability variables.

Selected LitScout evidence rows:

- `LIT-EP-001-001`: anionic/nonionic surfactant control of particle size and
  colloidal stability in seeded emulsion polymerization.
- `LIT-EP-001-003`: semibatch surfactant-free emulsion polymerization of butyl
  acrylate.
- `LIT-EP-001-002`: practical guide to latex particle size and distribution
  control in emulsion polymerization.

Go/no-go measurements emitted by the prediction report include particle size,
PDI, solids, conversion, residual monomer, coagulum mass, pH, temperature,
viscosity, and observations.

## Missing Skill Set

The current scaffold can generate a grounded next-experiment prediction, but the
report identifies six remaining gaps before the prediction should be treated as
reviewed or execution-ready:

- `safety_review_required`: the generated prediction contains a safety reminder,
  but no recorded approved SDS/SOP/thermal/PPE/waste review.
- `litscout_evidence_unreviewed`: generated LitScout evidence needs human
  review and notebook insertion before it is curated evidence.
- `formulation_quantities_missing`: the template EP-001 formulation rows lack a
  quantitative basis such as mass, volume, moles, weight percent, or
  concentration.
- `reagent_properties_missing`: Master Reagents lacks physical-property fields
  needed for calculation, especially monomer molecular weight/density and
  surfactant concentration.
- `result_metrics_missing`: the current experiment has DLS particle size but
  lacks enough outcome metrics for a stronger emulsion-polymerization
  prediction, especially PDI, conversion, coagulum mass, solids, and residual
  monomer.
- `historical_benchmarks_missing`: no same-process prior completed experiment
  benchmarks are available for comparison.

## Implementation Added

The `predict-next-experiment` CLI command now emits a standalone JSON audit with
separate `evidence`, `inference`, `go_no_go`, and `missing_skill_set` blocks.
This makes the LitScout bridge useful as a prediction workflow rather than only
as a search/export handoff.

Verification:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Current result: 153 tests passed.
