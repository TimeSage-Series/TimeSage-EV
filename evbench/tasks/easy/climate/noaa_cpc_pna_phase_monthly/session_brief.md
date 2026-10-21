# Task

You are an analyst tracking NOAA Climate Prediction Center's monthly
Pacific/North American (PNA) teleconnection index over a stretch of
consecutive months. The PNA is a standardised 500-hPa height-anomaly
index (sigma-units, base period 1950-2001) summarising a mid-latitude
wave-train pattern over the Pacific and North America -- positive PNA
means an amplified ridge over western North America and a deepened
trough over eastern North America (cold east, warm west); negative PNA
is the reverse pattern. Each month CPC publishes the latest PNA value
and you label its phase.

# Input

`timeseries.csv` in your working directory is the PNA monthly history from 1950-01 through
the current month, ascending in time, one row per calendar month. Columns:

- `year` -- 4-digit calendar year.
- `month` -- 1..12.
- `period_label` -- `YYYY-MM` string.
- `pna_value` -- the PNA index (standardised 500-hPa height-anomaly
  sigma-units, base period 1950-2001).
