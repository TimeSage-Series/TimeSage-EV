# Task

You are a respiratory-virus surveillance analyst tracking the weekly
US national RSV (respiratory syncytial virus) NAAT percent-positivity
published by CDC's NREVSS dashboard (Socrata dataset `rgnm-fkqb`),
filtered to `pathogen=RSV`, `level=National`, `subtype='Combined Type'`,
MMWR-week-ending Saturday. Each week you read the latest Saturday
percent_pos value off the CDC table and classify the current week's
RSV seasonal phase against the five-year same-MMWR-week historical
distribution.

Reference: https://data.cdc.gov/Public-Health-Surveillance/Percent-positivity-of-respiratory-viruses-by-nucle/rgnm-fkqb

# Input

`timeseries.csv` in your working directory is the cumulative weekly history of the CDC
NREVSS RSV percent-positivity series, ascending in time, one row per
MMWR week. The CSV spans the full series start (~2019-W27) through
the current MMWR week so you can recompute the 5-year same-week
baseline yourself. When the session advances one ISO week, exactly one
new row is appended at the bottom. Columns:

- `week_ending` — the Saturday MMWR week-ending date (YYYY-MM-DD).
- `iso_week` — ISO week label, in `YYYY-Www` form.
- `percent_pos` — Weekly US national RSV NAAT percent positive (0-100).
