# Task

You are a freight-and-trucking-cost analyst tracking the weekly
national-average US #2 diesel pump price published by the U.S. Energy
Information Administration (EIA) and mirrored on FRED as series
`GASDESW` — the all-sellers national average retail diesel price in
USD per gallon. Each week you read the latest Monday observation off
the FRED snapshot and report which fixed price band it falls into.

Reference: https://www.eia.gov/petroleum/gasdiesel/

# Input

`timeseries.csv` in your working directory is the cumulative weekly history of the
GASDESW series sampled at the Monday observation date (the EIA
publishes the survey result every Monday for the prior Monday's
nationally averaged sample). It is ascending in time, one row per ISO
week, and when the session advances to the next ISO week exactly one
new row is appended at the bottom. Columns:

- `observation_date` — the Monday date (YYYY-MM-DD) on which EIA
  reported the national-average pump price.
- `iso_week` — ISO week label of that Monday, in `YYYY-Www` form.
- `price_usd_per_gal` — US national-average retail #2 diesel pump
  price, USD per gallon.
