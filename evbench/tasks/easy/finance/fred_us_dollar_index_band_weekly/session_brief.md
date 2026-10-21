# Task

You are a foreign-exchange analyst tracking the weekly US-dollar
index published by the Federal Reserve / FRED as series `DTWEXBGS` —
the Nominal Broad U.S. Dollar Index (Goods + Services, trade-weighted,
Jan 2006 = 100). Each ISO week you read the Friday close (or the
nearest prior trading-day close within the same ISO week if Friday is
a US bank holiday) and report which fixed USD-strength band it falls
into.

Reference: https://fred.stlouisfed.org/series/DTWEXBGS

# Input

`timeseries.csv` in your working directory is the cumulative weekly history of the FRED
DTWEXBGS Friday closes. It is ascending in time, one row per ISO week,
and when the session advances to the next ISO week exactly one new
row is appended at the bottom. Columns:

- `week_ending` — the Friday week-ending date (YYYY-MM-DD).
- `iso_week` — ISO week label, in `YYYY-Www` form.
- `dxy_index` — Friday close of FRED DTWEXBGS (Nominal Broad U.S.
  Dollar Index, Goods + Services, Jan 2006 = 100). When the Friday is
  a US bank holiday the close used is the most recent prior weekday
  inside the same ISO week.
