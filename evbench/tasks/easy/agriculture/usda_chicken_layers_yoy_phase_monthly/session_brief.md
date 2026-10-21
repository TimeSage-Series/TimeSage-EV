# Task

You are a poultry-markets analyst tracking the USDA NASS *Chickens
and Eggs* monthly report's headline US chicken layer flock figure
over a stretch of consecutive data months. The Chickens and Eggs
report is released around the 20th of each calendar month, reporting
the prior calendar month's average layer flock size and egg production
figures. Each month you compare the latest data month's average layer
flock with the same calendar month one year earlier and report the
year-over-year (YoY) phase: whether the US layer flock is in
`expansion`, `contraction`, or `steady` versus a year ago.

Reference: https://esmis.nal.usda.gov/publication/chickens-and-eggs

# Input

`timeseries.csv` in your working directory is the cumulative US layer flock history as
known on the latest report's release date. Rows are ascending in time,
one per data month. Columns:

- `data_year` -- 4-digit year of the data month.
- `data_month` -- 1..12 of the data month.
- `period_label` -- `YYYY-MM` of the data month.
- `layers_klb` -- US total layer flock, average during the data
  month, in 1,000 head (USDA NASS published precision), as first
  published in the report for that month.
- `layers_revised_klb` -- the same figure as revised by a later report
  (each report restates the same month one year earlier). Empty until
  such a restatement has been published.

Some data months are missing (USDA did not publish them).
