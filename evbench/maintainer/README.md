# `evbench/maintainer/`

Build code for the scenario corpus. None of it is needed to *run* an
evaluation — a plain clone is already complete for that. It matters when you
update the benchmark to new periods or verify its integrity.

```
evbench/maintainer/
├── easy/ middle/ hard/   per-scenario build code: scenario.json, scripts/
├── lib/                  modules the per-scenario scripts import
├── pipeline/             cross-scenario refresh: download → format → compare → publish
└── corpus/               integrity checks and the hosted source binaries
```

**`lib/`** — imported by the scenario scripts, which put this directory on
`sys.path` and import the modules by bare name.

| Module | Purpose |
|---|---|
| `source_tree.py` | `SourceTree`: addresses `source/<period>/` as if it were the old flat `gt_source/` / `timeseries_source/`. |
| `instance_file.py` | `write_instance()`: writes `instances/<p>/instance.json` for each scenario's `template_vars.py`. |
| `narrative_extract.py` | Shared narrative-block builder imported by 17 scenarios' `format.py`. |

**`pipeline/`** — run in this order when extending the corpus.

| Script | Purpose |
|---|---|
| `download_all.sh` | Batch-download every scenario's reports and time series. |
| `format_all.sh` | Convert downloaded `source/` into per-period instances. |
| `scenario_cmd.py` | Resolve the arguments each pipeline step needs; used by both batch drivers. |
| `compare_reference.py` | Diff regenerated instances against the released corpus. |
| `publish_periods.py` | Append periods newer than the last released one to `evbench/scenarios/`. |

**`corpus/`**

| Script | Purpose |
|---|---|
| `validate_scenarios.py` | Repo-wide structural + leakage validation. Run after any data update. |
| `fetch_gt_source.py` | Download the source PDFs/XLS from Hugging Face into `evbench/scenarios/` (easy) and `scenarios_unfinished/` (middle, hard). |
| `gt_source_manifest.json` | Path → sha256 → size for the 1116 hosted binaries. |

## Refreshing the source data

```bash
evbench/maintainer/pipeline/download_all.sh --install-deps        # all 60, one scenario at a time
evbench/maintainer/pipeline/download_all.sh -t easy               # one tier
evbench/maintainer/pipeline/download_all.sh -s cboe_vix_volatility_regime_state
evbench/maintainer/pipeline/download_all.sh --dry-run             # print the commands, run nothing
evbench/maintainer/pipeline/download_all.sh -j 4                  # parallel, if the publishers tolerate it
```

Roughly 2.4 GB from live publisher servers. It runs serially by default —
these are government and intergovernmental sites and parallel requests earn
rate limits. Each scenario logs to `logs/download/<id>.log` and stamps
`<id>.done` on success, so a re-run resumes; `--redo` ignores the stamps.

`TIMESAGE_DATA_ROOT` redirects the output, which is the safe way to try a run
without touching the committed corpus:

```bash
TIMESAGE_DATA_ROOT=/tmp/probe evbench/maintainer/pipeline/download_all.sh -s noaa_cpc_ao_monthly_phase
```

Two scenarios need a free API key and are skipped without one:
`usda_crop_progress_weekly_brief` (`NASS_API_KEY`) and
`eia_wpsr_weekly_petroleum_brief` (`EIA_API_KEY`).

Expect a fresh download to differ from the committed corpus. Snapshot
filenames carry the capture date; some downloaders fetch a wider archive than
the instance window; and CDC, HHS and similar agencies revise past weeks. That
churn is the benchmark being live, not a fault.

## Validating the corpus

```bash
python evbench/maintainer/corpus/validate_scenarios.py --all             # exits non-zero on any failure
python evbench/maintainer/corpus/validate_scenarios.py --tier easy -v    # one tier, warnings included
python evbench/maintainer/corpus/validate_scenarios.py --all --strict    # also fail on answer degeneracy
python evbench/maintainer/corpus/validate_scenarios.py --all --json report.json
```

Gates:

| Gate | Checks |
|---|---|
| **F** files | 4 core instance files, 7 task-contract files in `evbench/tasks/`, the pipeline scripts, none empty; every `instance.json` fills its question template |
| **S** schema | every `ground_truth.json` has the `required` keys of the task's `answer_schema.json`, with matching types |
| **T** timeseries | `instances/<p>/timeseries.csv` parses and has data rows of consistent width |
| **E** evidence | `gt_evidence.md` is substantive and cites `gt_source/` or `timeseries.csv` |
| **X** cross-instance | categorical answer fields are not constant across periods |
| **L** leakage | no CSV row beyond the instance period; `visible_reports.json` excludes the current period |

Gate **X** reports at `warn` by default. A constant categorical field is usually
a real property of the series — the top U.S. crude-oil source country really is
Canada every month — so it should not fail a structural check. Use `--strict`
when you want degeneracy to block.

Gate **L** deliberately does **not** flag `gt_evidence.md` for citing its own
period's source. That file is grader-side material and is *supposed* to quote
the answer's source. Leakage is about what reaches the agent's sandbox, and
`evsandbox/evsandbox/world.py` filters `gt_source/` to `stem < period` when it
materializes one.

Gate **L** reads `visible_reports.json` under either the `visible` or
`visible_reports` key. The upstream dashboard check read only the latter while
every builder wrote the former, so it silently returned "n/a" for every
scenario it was meant to guard.

## Restoring the source binaries

The 1116 report PDFs and Excel workbooks (2.3 GB) are hosted as a Hugging Face
dataset rather than committed, so the git repo stays around 120 MB and needs no
Git LFS. `instances/` contains no binaries at all, which is why the evaluation
loop is fully offline without them.

```bash
pip install huggingface_hub
python evbench/maintainer/corpus/fetch_gt_source.py                  # all 1116 files
python evbench/maintainer/corpus/fetch_gt_source.py --tier hard
python evbench/maintainer/corpus/fetch_gt_source.py --scenario eia_wpsr_weekly_petroleum_brief
python evbench/maintainer/corpus/fetch_gt_source.py --verify-only    # checksum what is already here
```

You need them only to re-run a scenario's `scripts/format.py`, or to let an
agent read the original reports inside the sandbox.

## Provenance and known limitations

`lib/`, `pipeline/` and `corpus/` are a **reimplementation**. The upstream working repository kept
its pipeline tooling in an untracked `tools/` directory that was never
committed and did not survive to the public release. Two things were lost:

**1. `narrative_extract`.** Seventeen ``format.py gt`` scripts import
`build_narrative_md_block` and `load_source_text` from it. The markdown
contract — section headings, the three trigger vocabularies, the default label
`"Verbatim bullets / executive summary"`, the 3000-character default budget —
was recovered exactly from the 1485 committed `gt_evidence.md` files and is
reproduced verbatim. The PDF text path was verified byte-identical against
`pypdf` page extraction. The HTML path is a faithful reimplementation but not a
bit-exact clone: the original's block-boundary whitespace and its exact
truncation boundary could not be recovered. **Consequence:** regenerating a
*pre-existing* period may produce whitespace-level diffs in `gt_evidence.md`.
Output for *new* periods is correct and self-consistent, which is the case that
matters for keeping the benchmark live.

**2. The oracle layer.** `grounding_rules/<scenario_id>.py` (60 per-scenario
derivation rules) and `validate_oracles.py` are gone. `validate_scenarios.py`
covers the gates checkable from the corpus alone (F, S, T, E, X, L) but not the
two that needed those modules: **R** (rule reproducibility — recompute the
answer from the raw series and diff against `ground_truth.json`) and **P**
(quote grounding — assert every quoted span appears verbatim in its source).
The dashboard endpoints that read the oracle modules were removed rather than
shipped dead.

**3. Anonymization is not reproducible.** The committed corpus was
PII-scrubbed before release: personal names became `PERSON_A`…, and phone
numbers and email addresses became `[REDACTED]`. This affects 21 scenarios and
about 3160 occurrences. The scrubber also lived in the lost `tools/`.
**Re-running ``format.py gt`` on an affected scenario will re-introduce the
original names, phone numbers, and email addresses from the source reports.**
Affected scenarios, worst first:

```
middle/transportation/ata_truck_tonnage_monthly_brief
middle/transportation/portla_monthly_cargo_stats_brief
middle/climate/noaa_ncei_us_climate_monthly_brief
middle/climate/noaa_ncei_global_climate_monthly_brief
hard/transportation/cass_freight_index_monthly_analytical
hard/climate/noaa_cpc_enso_diagnostic_discussion_monthly
middle/finance/dallas_fed_texas_manufacturing_brief
hard/finance/ecb_monetary_policy_statement_attribution
middle/agriculture/usda_drought_monitor_us_regional_brief
hard/climate/iri_enso_quick_look_monthly
middle/healthcare/bls_jolts_healthcare_monthly_brief
hard/healthcare/cdc_resp_net_weekly_dominant_pathogen
hard/finance/bea_pce_inflation_monthly_attribution
middle/transportation/bls_ppi_freight_transport_modes_monthly_brief
hard/agriculture/usda_fas_world_agricultural_production_monthly_attribution
middle/healthcare/bls_us_health_employment_monthly_brief
middle/agriculture/usda_wasde_crop_balance_monthly_brief
easy/climate/noaa_cpc_mjo_phase_weekly
easy/agriculture/usda_cold_storage_pork_band_monthly
easy/agriculture/usda_cold_storage_butter_band_monthly
easy/agriculture/usda_chicken_layers_yoy_phase_monthly
```

Re-scrub before committing regenerated instances for any of these.
