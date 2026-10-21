# Task

You are an aviation-industry recovery analyst tracking US TSA airport
checkpoint passenger volumes published at
`https://www.tsa.gov/travel/passenger-volumes`. Each ISO week you
read the latest weekly throughput off the TSA snapshot, compare it
to the same-week-of-year 2019 baseline (the standard pre-pandemic
benchmark), and report which recovery band the week falls into.

Reference: https://www.tsa.gov/travel/passenger-volumes

# Input

`timeseries.csv` in your working directory is the cumulative weekly aggregate of TSA
checkpoint counts. It is ascending in time, one row per ISO week,
and when the session advances to the next ISO week exactly one new
row is appended at the bottom. Columns:

- `week_ending` — the Sunday week-ending date (YYYY-MM-DD) of the
  ISO week.
- `iso_week` — ISO week label, in `YYYY-Www` form.
- `throughput` — sum of TSA daily checkpoint counts across the
  Monday-Sunday days of that ISO week.
- `baseline_2019` — sum of TSA daily counts for the SAME ISO-week-
  of-year in calendar year 2019 (pre-pandemic baseline).
