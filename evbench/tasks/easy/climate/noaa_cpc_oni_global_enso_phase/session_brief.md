# Task

You are an analyst tracking NOAA Climate Prediction Center's Oceanic
Niño Index (ONI) over a stretch of consecutive 3-month overlapping
seasons. The ONI is the canonical operational indicator of the El Niño
/ Southern Oscillation (ENSO) state — a 3-month running mean of
sea-surface-temperature (SST) anomalies in the Niño 3.4 region
(5°N–5°S, 170°W–120°W) relative to the 1991–2020 base period, in °C.
Each month a new overlapping season is appended (DJF, JFM, FMA, …,
NDJ); you read the latest row and label the ENSO phase for that
season under NOAA CPC's ±0.5 °C threshold rule.

Reference: https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/ONI_v5.php

# Input

`timeseries.csv` in your working directory is the cumulative ONI history from DJF 1950
through the current season, ascending in time, one row per overlapping
3-month season. Columns:

- `season` — 3-letter season code (one of `DJF`, `JFM`, `FMA`, `MAM`,
  `AMJ`, `MJJ`, `JJA`, `JAS`, `ASO`, `SON`, `OND`, `NDJ`).
- `year` — year of the centered month of the season.
- `season_label` — `YYYY-SEAS` form, where SEAS is the `season` code.
- `centered_month` — calendar month number (1=Jan … 12=Dec) of the
  centered month of the season.
- `nino34_total_c` — TOTAL column from the NOAA CPC ONI file: Niño
  3.4 region SST in °C.
- `nino34_anomaly_c` — the ONI value: ANOM column = anomaly of Niño
  3.4 SST in °C relative to the 1991–2020 base period.
