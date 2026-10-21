# Task

You are an energy-markets analyst tracking the weekly close of West
Texas Intermediate (WTI) crude oil daily spot price, published by the
Federal Reserve Bank of St. Louis as FRED series `DCOILWTICO` — the
US benchmark light-sweet crude price in USD per barrel. Each ISO
week you read the latest Friday-close price off the FRED snapshot
and report which fixed price band it falls into.

Reference: https://fred.stlouisfed.org/series/DCOILWTICO

# Input

`timeseries.csv` in your working directory is the cumulative weekly history of the
DCOILWTICO series sampled at the Friday close (with fallback to the
most recent prior weekday in the same ISO week when Friday is a
market-closed US equity-market holiday). It is ascending in time, one
row per ISO week, and when the session advances to the next ISO week
exactly one new row is appended at the bottom. Columns:

- `observation_date` — the trading-day date (YYYY-MM-DD) that the
  weekly close was sampled on: the Friday of the ISO week, or the
  most recent prior weekday if Friday was a market-closed holiday.
- `iso_week` — ISO week label, in `YYYY-Www` form.
- `price_usd_per_bbl` — WTI crude oil daily spot price, USD per
  barrel.
