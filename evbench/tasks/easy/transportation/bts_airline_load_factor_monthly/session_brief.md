# Task

You are a U.S. aviation-industry analyst tracking the BTS monthly
system-wide passenger load factor (the share of available seat-miles
that are revenue passenger-miles). The series is mirrored on FRED
under id `LOADFACTOR` and is published monthly with a ~2-month lag.
Each month you report whether the latest reading is the maximum
across the trailing 12-month window (a "year-high").

Reference: https://www.bts.gov/topics/airlines-and-airports/airline-traffic-data

# Input

`timeseries.csv` in your working directory is the cumulative monthly U.S. system-wide
passenger load factor series, ascending in time, one row per data
month. Columns:

- `data_month` — Data month in `YYYY-MM` form.
- `load_factor` — U.S. system-wide passenger load factor (%) for the
  data month, as published by BTS / mirrored by FRED.
