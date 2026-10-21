# Task

You are a red-meat-markets analyst tracking the USDA NASS *Cold
Storage* monthly report's headline US **Total pork** stocks figure
over a stretch of consecutive data months. The Cold Storage report is
released around the 23rd-25th of each calendar month, reporting
end-of-prior-month stocks for cheeses, butter, meats, poultry, fruit,
and vegetables in US refrigerated warehouses. Each month you compare the latest data month's stocks with the same
calendar month in each of the previous five years, and report whether
pork stocks for that data month fall into the `tight`, `low`,
`normal`, or `heavy` band.

Reference: https://esmis.nal.usda.gov/publication/cold-storage

# Input

`timeseries.csv` in your working directory is the cumulative US Total pork cold-storage
history. Rows are ascending in time, one per data month. Columns:

- `data_year` -- 4-digit year of the data month.
- `data_month` -- 1..12 of the data month.
- `period_label` -- `YYYY-MM` of the data month.
- `pork_stocks_mlb` -- US Total pork stocks at end of data month, in
  million pounds (the NASS frozen-red-meat-table 'Total pork' row,
  current-data-month column, converted from 1,000 pounds).
