# Core-Shell CSP Next Experiment Prediction

Date: 2026-06-15

Experiment id: `CSP-GD-001`

Source scope: Google Drive core-shell emulsion polymerization documents and the `Emulsion Polymerization` Google Sheet, plus a local LitScout session named `labnotebook/core-shell-csp-google-drive`.

## Source Read

Drive sources used:

- `2023-09-12 Core Shell Particle patentability summary`: target effective core-shell particles are 200-350 nm with monomodal PSD; semibatch polymerization is required; SDS alone can phase-separate during monomer feed; mixed ionic/nonionic surfactant is required; branched non-APE fatty alcohol ether surfactants such as Tergitol-type DP 35-40 materials are called out as stabilizing large solketal acrylate rubber cores.
- `Free Radical Core Shell Emulsion Polymerization.docx`: use seeded core growth, stable premulsion over the 3-4 hour feed, DLS to detect new-particle nucleation, redox at lower temperature when morphology control is needed, and 50 micron sieve workup.
- `Emulsion Polymerization` Google Sheet:
  - `EP-321 Variable Feed Rates CSP-Solektal-50-50`: 50/50 butyl acrylate/solketal acrylate core design with 88 nm seed, variable core feed, and estimated final particle size in the 330-340 nm range.
  - `EP-323 Variable Feed Rates SFS Trial 1`: high redox-flux SFS/TBHP trial; estimated core radical flux around 7e-5 mol/min/L in the core feed.
  - `EP-324 Variable Feed Rates SFS Trial 2`: lower redox-flux SFS/TBHP trial; estimated core radical flux around 1.7e-5 to 1.9e-5 mol/min/L, 88 nm seed, about 6 ms/g seed requirement per L water, and target final estimated particle size about 342 nm.

No measured DLS, coagulum, conversion, or actual-result rows were found in the scanned latest tabs. This is therefore a planning prediction from formulation logic, worksheet calculations, Drive notes, and literature context, not a data-fitted outcome model.

## LitScout Context

Commands run locally:

```bash
litscout search multi "seeded emulsion polymerization core shell latex particle size surfactant redox initiator monomer feed glycidyl methacrylate" --sources openalex,crossref,semantic_scholar --depth light --limit 35 --save --session-name labnotebook/core-shell-csp-google-drive
litscout search multi "fundamentals emulsion polymerization surfactant particle nucleation monomer feed initiator latex particle size" --sources openalex,crossref,semantic_scholar --depth light --limit 25 --save --session-name labnotebook/core-shell-csp-google-drive
litscout search multi "Lovell Schork Fundamentals of Emulsion Polymerization Biomacromolecules 2020" --sources openalex,crossref,semantic_scholar --depth light --limit 10 --save --session-name labnotebook/core-shell-csp-google-drive
litscout sessions export labnotebook/core-shell-csp-google-drive --format json --json-array --output artifacts/litscout-core-shell-csp-google-drive.json
PYTHONPATH=src python3 -m lab_notebook_agent.cli litscout-semantic-search --input artifacts/litscout-core-shell-csp-google-drive.json "seeded core shell latex emulsion polymerization particle size surfactant nucleation redox initiator monomer feed glycidyl methacrylate solketal acrylate" -k 15 --output artifacts/core-shell-csp-litscout-semantic-matches.json
PYTHONPATH=src python3 -m lab_notebook_agent.cli evidence-from-litscout --input artifacts/litscout-core-shell-csp-google-drive.json --experiment-id CSP-GD-001 --query "seeded core shell latex emulsion polymerization particle size surfactant nucleation redox initiator monomer feed glycidyl methacrylate solketal acrylate" --limit 12 --output artifacts/core-shell-csp-literature-evidence.json
```

Highest-signal LitScout hits included seeded/core-shell emulsion polymerization, acrylate latex, GMA-containing seeded systems, secondary nucleation, PSD modeling, monomer transport, and redox free-radical polymerization:

- `10.1021/ma049496l`: seeded emulsion polymerization of core-shell nanoparticles with controlled particle size.
- `10.3390/ijms9030342`: core-shell acrylate latex with butyl acrylate, glycidyl methacrylate, ammonium persulfate, and emulsion polymerization concepts.
- `10.6000/1929-5995.2016.05.02.2`: secondary particle nucleation in methyl methacrylate miniemulsion polymerization.
- `10.1295/polymj.pj2005184`: methacrylate latex particle-size changes as a function of main reaction parameters.
- `10.1002/mren.201600059`: PSD modeling in emulsion polymerization.
- `10.1021/acs.biomac.4c00412`: monomer equilibrium and transport in emulsion and miniemulsion polymerization.
- `10.1016/j.progpolymsci.2019.04.003`: redox two-component initiated free-radical polymerization.

The exact Lovell/Schork fundamentals paper cited in the Drive note did not resolve in the LitScout session, so it is treated as Drive-note support rather than LitScout support.

## Prediction

Run `CSP-GD-001` as a solketal-containing version of the EP-324 low-flux design, but add a controlled non-APE branched nonionic surfactant component from the patentability note.

Predicted result: the best next single experiment is a 50/50 BA/SKA core-shell run with moderate redox flux and a mixed ionic/branched-nonionic surfactant package. It should be more likely to keep a monomodal 260-310 nm core and 330-345 nm final core-shell particle than either a high-flux EP-323-style SFS/TBHP run or a purely ionic package. The expected benefit is lower secondary nucleation and less feed-period instability while retaining enough radical flux to finish conversion and shell growth.

Confidence: medium. The design is well aligned with the worksheet and Drive notes, but the latest sheets do not include measured outcomes.

## Proposed Recipe Delta

Base the run on `EP-321` for the solketal core and `EP-324` for the lower redox-flux trajectory.

Seed:

- Use the 88 nm BA seed basis from the EP-321/EP-324 family.
- Target seed requirement: about 6 ms/g per L water, matching EP-324 order of magnitude.
- Hold feed start until after the seed shot temperature peak has stabilized. The sheet note says the seed peaked at 71.9 C and the feed should begin only after equilibration; use a concrete acceptance criterion such as less than 1 C drift over 5 minutes.

Core:

- Core monomer: BA 49.85 pphm, solketal acrylate 49.85 pphm, allyl methacrylate 0.2 pphm, BDDMA 0.1 pphm, tert-dodecyl mercaptan 0.03 pphm.
- Reactor charge: seed latex 11 pphm, DI water 50 pphm, EDTA solution 1 pphm, ferrous sulfate solution 1 pphm.
- Surfactant: keep Aerosol MA-80 at 1.6 pphm and add a low branched nonionic Tergitol-type DP 35-40 surfactant level, initially 0.3-0.5 pphm active. Keep total core surfactant active near the EP-321/EP-324 range, about 0.95-1.10 percent BOTW, rather than the higher EP-323 loading.
- Redox: target a core radical-flux window between EP-324 and EP-323, about 2e-5 to 4e-5 mol/min/L. A practical first pass is TBHP around 1.0 wt% and SFS around 1.5 wt% at EP-324-style feed volumes, then recalculate the sheet before running.
- Core feed: keep the 180 minute variable feed ramp from EP-324: 5%, 7%, 8%, 10%, 18%, 22%, 20%, 10%, followed by a 30 minute redox hold.
- Temperature: keep the redox core around 60 C internal / 65 C oil bath unless the recalculated heat balance argues otherwise.

Shell and functional shell:

- Keep the EP-324 shell architecture to isolate the core/surfactant/redox change.
- Shell monomer: MMA 87 pphm, EA 12 pphm, allyl methacrylate 0.1 pphm, BDDMA 0.05 pphm, tert-dodecyl mercaptan 0.1 pphm, Aerosol MA-80 1.6 pphm.
- Functional shell: MMA 46 pphm, EA 4 pphm, GMA 50 pphm, Aerosol MA-80 1.6 pphm, Rhodapex EST-30 0.3 pphm, COPS-1 1 pphm, Surfmer/Rhodapex CL 910 0.5 pphm.
- Feed shell and functional shell only if the core checkpoint passes.

## Go/No-Go Checkpoints

- Premulsion stability: no visible creaming, phase split, or grit over the expected 3-4 hour feed window before charging the full run.
- Core DLS: sample at seed, 15, 60, 120, 180, and 210 minutes. Continue to shell only if the core is monomodal and roughly 260-310 nm after hold.
- New-particle nucleation: stop or branch the run if a persistent small-particle mode below 120 nm appears during core feed.
- Coagulum: pass through a 50 micron sieve and record retained solids. Continue only if coagulum is below the lab's acceptable threshold; use less than 0.5 wt% as the first planning target.
- Conversion/residual monomer: do not proceed to shell if the moderate redox condition leaves obvious residual monomer or odor after the hold.
- pH and solids: record pH at seed/core/shell/functional-shell endpoints and verify final solids against the worksheet target before comparing DLS.

## Failure Modes To Watch

- Too much nonionic surfactant may stabilize new particles instead of only stabilizing the growing seed population.
- Too little radical flux may improve colloidal stability but leave incomplete conversion or weak shell grafting.
- Solketal acrylate polarity may change monomer transport relative to the BA-only EP-324 design.
- GMA functional shell can introduce gel or hydrolysis risk if pH, residence time, or redox timing drift.

## Minimal Control

If material and time permit, pair `CSP-GD-001` with a same-day control that deletes only the added Tergitol-type nonionic from the core premulsion while keeping the redox window and feed schedule identical. The decision metric is not only final size; it is monomodal PSD, low coagulum, and no small-particle shoulder during core growth.

## Safety Note

This prediction is not a safety-approved SOP. Before execution, review current SDS entries, peroxide/reductant compatibility, monomer inhibitor handling, needle/syringe-pump hazards, condenser and purge setup, thermal runaway controls, PPE, and waste handling with the lab's approved procedure.
