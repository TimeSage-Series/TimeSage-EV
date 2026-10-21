# Task

You are an analyst monitoring CDC NWSS COVID-19 wastewater activity at a single
LA-county sentinel site. Each MMWR week (Saturday-ending) you report the
week-over-week (WoW) direction of the site's wastewater viral activity index.

Reference: https://www.cdc.gov/nwss/rv/COVID19-currentlevels.html

# Input

`timeseries.csv` in your working directory is the cumulative NWSS history for site `ID:113`
filtered to SARS-CoV-2, ascending in time, one row per MMWR week. Columns:

- `week_end` — Saturday-ending date in `YYYY-MM-DD` form.
- `iso_week` — ISO-week label in `YYYY-Www` form.
- `site_wval` — numeric wastewater viral activity index.
