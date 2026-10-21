# Task

You are a macro analyst tracking the Sahm Rule Recession Indicator
(FRED series `SAHMCURRENT`), a real-time monthly US statistic that
flags the start of a recession when the 3-month moving average of the
national unemployment rate has risen by at least 0.50 percentage
points above its minimum during the previous 12 months. The series is
reported in percentage points of unemployment-rate change. Each month
you read the latest published value off the FRED snapshot and report
which recession-signal bucket the headline indicator is in.

Reference: https://fred.stlouisfed.org/series/SAHMCURRENT

# Input

`timeseries.csv` in your working directory is the cumulative monthly history of the
SAHMCURRENT series, ascending in time, one row per calendar month
with a first-of-month observation_date. When the session advances to
the next month, exactly one new row is appended at the bottom.
Columns:

- `observation_date` — first-of-month ISO date (YYYY-MM-DD) of the
  monthly observation.
- `month_label` — month label in `YYYY-MNN` form.
- `sahm_value` — the Sahm-rule indicator value in percentage points
  (3-month-MA national unemployment rate minus its trailing 12-month
  minimum).
