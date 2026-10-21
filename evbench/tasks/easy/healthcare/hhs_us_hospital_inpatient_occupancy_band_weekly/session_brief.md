# Task

You are a hospital-capacity analyst tracking the weekly US inpatient
bed occupancy percent published by the U.S. Centers for Disease Control
and Prevention (CDC) in the Weekly Hospital Respiratory Data (HRD)
Metrics by Jurisdiction dataset (Socrata id `ua7e-t2fy`), column
`pctinptbedsocc` for jurisdiction `USA` — the percent of US inpatient
beds occupied, MMWR-week-ending Saturday. Each week you read the
latest Saturday percent value off the CDC table and report which fixed
occupancy band it falls into.

Reference: https://data.cdc.gov/Public-Health-Surveillance/Weekly-Hospital-Respiratory-Data-HRD-Metrics-by-Ju/ua7e-t2fy

# Input

`timeseries.csv` in your working directory is the cumulative weekly history of the CDC US
inpatient-occupancy series sampled at the published Saturday
week-ending date. It is ascending in time, one row per ISO week, and
when the session advances to the next ISO week exactly one new row is
appended at the bottom. Columns:

- `week_ending` — the Saturday MMWR week-ending date (YYYY-MM-DD) for
  which CDC reports the percent value.
- `iso_week` — ISO week label, in `YYYY-Www` form.
- `pctinptbedsocc` — Weekly U.S. percent of inpatient beds occupied
  (percent, 0-100, jurisdiction='USA').
