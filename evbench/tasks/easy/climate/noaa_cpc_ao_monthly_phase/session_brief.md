# Task

You are an analyst tracking NOAA Climate Prediction Center's monthly
Arctic Oscillation (AO) index over a stretch of consecutive months. The
AO is a standardised sea-level-pressure anomaly index (sigma-units,
base period 1979–2000) summarising the strength of the Arctic polar
vortex from pressure patterns north of 20°N — positive AO means a
strong vortex confining cold air to high latitudes, negative AO a weak
vortex letting cold air spill into mid-latitudes. Each month CPC
publishes the latest AO value and you label its phase.

# Input

`timeseries.csv` in your working directory is the AO monthly history from 1950-01 through
the current month, ascending in time, one row per calendar month. Columns:

- `year` — 4-digit calendar year.
- `month` — 1..12.
- `period_label` — `YYYY-MM` string.
- `ao_value` — the AO index (standardised SLP-anomaly sigma-units,
  base period 1979–2000).
