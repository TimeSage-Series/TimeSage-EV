# Task

You are an analyst tracking the USDA NASS *Cattle on Feed* monthly
report over a stretch of consecutive release months. *Cattle on Feed*
is the USDA's headline series on US feedlot inventory, released around
the 20th of each month, with each report covering placements made in
the **prior calendar month** (the *data month*). Each month you read
the latest release and report the year-over-year (YoY) direction of
placements: whether feedlot placements during that data month were
above, below, or equal to placements during the **same calendar month
one year earlier**.

Reference: https://esmis.nal.usda.gov/publication/cattle-feed

# Input

`timeseries.csv` in your working directory is the cumulative USDA Cattle on Feed release
history from the earliest available raw release through the current
release month, ascending in time, one row per release month. Columns:

- `release_label` — `YYYY-MM` of the report release.
- `release_year` — 4-digit calendar year of the release.
- `release_month` — 1..12, calendar month of the release.
- `data_month_name` — full English month name of the
  data month the placements figure covers (the prior calendar month
  relative to the release).
- `prior_year` — the calendar year of the same data month one year
  earlier, i.e. the year the YoY comparison is made against.
- `placements_million` — placements in feedlots, in million head, for
  the data month.

The same data month one year earlier is the row whose `release_label`
is exactly 12 months before the current one; it has the same
`data_month_name`.
