It's now {{release_month_long}} and USDA NASS has just released the Cold Storage report for data month {{data_month_long}}. I need a brief on this release:

Q1: Compared with the same month in each of the previous five years, what is the butter storage band for {{data_month_long}}?
Options: `tight` / `low` / `normal` / `heavy`
Explanation: Take the reference window: the five most recent earlier rows whose
`data_month` equals the latest row's (normally the same month in each
of the previous five calendar years). Over their `butter_stocks_mlb` values
compute

- `min`   -- the minimum,
- `mean`  -- the arithmetic mean,
- `sigma` -- the population standard deviation (divide by 5, not 4),

then classify the latest row's `butter_stocks_mlb` (`stocks`):

- `tight`:  `stocks <  min`
- `low`:    `min <= stocks < mean - 0.5 * sigma`
- `normal`: `mean - 0.5 * sigma <= stocks < mean + 0.5 * sigma`
- `heavy`:  `stocks >= mean + 0.5 * sigma`

Q2: Wrap up with a 1–3 sentence factual summary covering the current period, the `butter_storage_band` tag, and at least one supporting numeric value from the latest CSV row.
Options: free text, at most 800 characters.
