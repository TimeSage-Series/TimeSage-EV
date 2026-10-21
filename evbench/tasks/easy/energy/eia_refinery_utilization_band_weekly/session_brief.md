# Task

You are an oil-products analyst tracking the weekly US refinery
operable-capacity utilization rate published by the U.S. Energy
Information Administration (EIA) as series `WPULEUS3` — the percent
of US refinery operable capacity actually running, week-ending Friday.
Each week you read the latest Friday percent value off the EIA
snapshot and report which fixed utilization band it falls into.

Reference: https://www.eia.gov/petroleum/weekly/

# Input

`timeseries.csv` in your working directory is the cumulative weekly history of the EIA
refinery-utilization series sampled at the published Friday
week-ending date. It is ascending in time, one row per ISO week, and
when the session advances to the next ISO week exactly one new row is
appended at the bottom. Columns:

- `week_ending` — the Friday week-ending date (YYYY-MM-DD) for which
  EIA reports the percent value.
- `iso_week` — ISO week label, in `YYYY-Www` form.
- `utilization_pct` — Weekly U.S. percent utilization of refinery
  operable capacity (percent, 0-100).
