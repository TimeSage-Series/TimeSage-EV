# Task

You are a markets analyst tracking the CBOE Volatility Index (VIX),
the implied-volatility gauge for the S&P 500 published as FRED series
`VIXCLS` (daily close, sourced from Cboe). Practitioners commonly
summarise the VIX level into a small number of named "regimes" — calm,
typical, stressed, crisis — to characterise the prevailing equity-risk
environment. Each ISO week you read the latest Friday-close VIX value
off the FRED snapshot and report which fixed regime band it falls into.

Reference: https://fred.stlouisfed.org/series/VIXCLS

# Input

`timeseries.csv` in your working directory is the cumulative weekly history of the VIX
sampled at the Friday close (with fallback to the most recent prior
weekday in the same ISO week when Friday is a market-closed US
equity-market holiday). It is ascending in time, one row per ISO
week, and when the session advances to the next ISO week exactly one
new row is appended at the bottom. Columns:

- `observation_date` — the trading-day date (YYYY-MM-DD) that the
  weekly close was sampled on: the Friday of the ISO week, or the
  most recent prior weekday if Friday was a market-closed holiday.
- `iso_week` — ISO week label, in `YYYY-Www` form.
- `vix_close` — the CBOE VIX closing value for that day.
