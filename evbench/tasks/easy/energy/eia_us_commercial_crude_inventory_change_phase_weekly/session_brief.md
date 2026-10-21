# Task

You are an oil-products analyst tracking the weekly US commercial
crude oil stocks (excluding the Strategic Petroleum Reserve) published
by the U.S. Energy Information Administration (EIA) as series
`WCESTUS1` — total US ending stocks of crude oil in thousand barrels,
week-ending Friday. Each week you read the latest Friday stocks value
off the EIA snapshot, compute the week-over-week change in MILLION
barrels, and report which fixed inventory-change phase it falls into.

Reference: https://www.eia.gov/petroleum/weekly/

# Input

`timeseries.csv` in your working directory is the cumulative weekly history of the EIA
commercial-crude-stocks series sampled at the published Friday
week-ending date. It is ascending in time, one row per ISO week, and
when the session advances to the next ISO week exactly one new row is
appended at the bottom. Columns:

- `week_ending` — the Friday week-ending date (YYYY-MM-DD).
- `iso_week` — ISO week label, in `YYYY-Www` form.
- `stocks_thousand_bbl` — US commercial crude stocks excl. SPR, in
  THOUSAND barrels (the native EIA unit).
