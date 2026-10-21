# Task

You are a dairy-markets analyst tracking the USDA NASS *Cold Storage*
monthly report's headline US total butter stocks figure over a stretch
of consecutive data months. The Cold Storage report is released around
the 23rd-25th of each calendar month, reporting end-of-prior-month
stocks for cheeses, butter, meats, poultry, fruit, and vegetables in
US refrigerated warehouses. Each month you compare the latest data month's stocks with the same
calendar month in each of the previous five years, and report whether butter stocks
for that data month fall into the `tight`, `low`, `normal`, or `heavy`
band.

Reference: https://esmis.nal.usda.gov/publication/cold-storage

# Input

`timeseries.csv` in your working directory is the cumulative US butter cold storage
history. Rows are ascending in time, one per data month. Columns:

- `data_year` -- 4-digit year of the data month.
- `data_month` -- 1..12 of the data month.
- `period_label` -- `YYYY-MM` of the data month.
- `butter_stocks_mlb` -- total US butter stocks at end of data
  month, in million pounds (the NASS headline figure converted
  from 1,000 pounds).
