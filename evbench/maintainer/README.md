# Maintainer

Build code for the scenario corpus. Running an evaluation needs none of it —
only the published corpus in `evbench/scenarios/`. Use it to extend the
benchmark to new periods or to check the corpus.

```
evbench/maintainer/
├── easy/ middle/ hard/   one directory per scenario: scenario.json, scripts/
├── lib/                  modules the scenario scripts import
├── pipeline/             download → format → compare → publish
└── corpus/               validation, and restoring the source PDFs/XLS
```

Install the extra dependencies with `uv sync --extra maintainer`.

## Adding new periods

```bash
evbench/maintainer/pipeline/download_all.sh -t easy                    # fetch from the publishers
evbench/maintainer/pipeline/format_all.sh -t easy --with-ground-truth  # build instances
python evbench/maintainer/pipeline/compare_reference.py -t easy        # does it reproduce the release?
python evbench/maintainer/pipeline/publish_periods.py -t easy          # append only the new periods
python evbench/maintainer/corpus/validate_scenarios.py --all           # check the result
```

- Everything is written to `scenarios_wkspace/` first (or
  `$TIMESAGE_DATA_ROOT`). A scenario script run on its own, outside these
  drivers, writes to `evbench/scenarios/` unless that variable is set.
- Downloads hit live government sites, about 2.4 GB, one scenario at a time
  by default. Re-runs resume; `--dry-run` prints the commands; `-s <id>`
  picks one scenario.
- `usda_crop_progress_weekly_brief` needs `NASS_API_KEY` and
  `eia_wpsr_weekly_petroleum_brief` needs `EIA_API_KEY`; both are skipped
  without them.
- Fresh downloads differ from the release — publishers revise past data — so
  `publish_periods.py` never rewrites a released period.

## Validation

`validate_scenarios.py` exits non-zero on any failure; `--strict` also fails
on constant answers, `--json` writes a report.

| Gate | Checks |
|---|---|
| **F** files | core instance and task files exist and are non-empty; every question renders |
| **S** schema | `ground_truth.json` matches the task's `answer_schema.json` |
| **T** timeseries | `timeseries.csv` parses with consistent row width |
| **E** evidence | `gt_evidence.md` is substantive and cites its source |
| **X** cross-instance | categorical answers vary across periods (warning unless `--strict`) |
| **L** leakage | no data past the period reaches the agent |

## Source reports

The 1116 report PDFs and workbooks behind the corpus (2.3 GB) are hosted on
Hugging Face. They are needed only to rebuild a scenario or to let an agent
read past reports in its sandbox:

```bash
python evbench/maintainer/corpus/fetch_gt_source.py --tier easy     # or --scenario <id>, --verify-only
```

## Known limitations

- **Narrative evidence.** Regenerating a released period may show
  whitespace-level diffs in the narrative block of `gt_evidence.md`; new
  periods are unaffected.
- **No rule-level checks.** Validation does not recompute answers from the
  raw series or verify quoted spans against the source.
- **No anonymization.** The released corpus was PII-scrubbed (names →
  `PERSON_A`, phones and emails → `[REDACTED]`), but the scrubber is not
  included. **Re-running `format.py gt` re-introduces personal data** in
  these scenarios — re-scrub before publishing them:

  ```
  easy/agriculture/usda_chicken_layers_yoy_phase_monthly
  easy/agriculture/usda_cold_storage_butter_band_monthly
  easy/agriculture/usda_cold_storage_pork_band_monthly
  easy/climate/noaa_cpc_mjo_phase_weekly
  middle/agriculture/usda_drought_monitor_us_regional_brief
  middle/agriculture/usda_wasde_crop_balance_monthly_brief
  middle/climate/noaa_ncei_global_climate_monthly_brief
  middle/climate/noaa_ncei_us_climate_monthly_brief
  middle/finance/dallas_fed_texas_manufacturing_brief
  middle/healthcare/bls_jolts_healthcare_monthly_brief
  middle/healthcare/bls_us_health_employment_monthly_brief
  middle/transportation/ata_truck_tonnage_monthly_brief
  middle/transportation/bls_ppi_freight_transport_modes_monthly_brief
  middle/transportation/portla_monthly_cargo_stats_brief
  hard/agriculture/usda_fas_world_agricultural_production_monthly_attribution
  hard/climate/iri_enso_quick_look_monthly
  hard/climate/noaa_cpc_enso_diagnostic_discussion_monthly
  hard/finance/bea_pce_inflation_monthly_attribution
  hard/finance/ecb_monetary_policy_statement_attribution
  hard/healthcare/cdc_resp_net_weekly_dominant_pathogen
  hard/transportation/cass_freight_index_monthly_analytical
  ```
