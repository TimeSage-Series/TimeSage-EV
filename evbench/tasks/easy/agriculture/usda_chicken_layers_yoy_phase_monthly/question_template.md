It's now {{release_month_long}} and USDA NASS has just released the Chickens and Eggs report for data month {{data_month_long}}. I need a brief on this release:

Q1: Year over year (YoY): compared with {{prior_year_data_month_long}}, is the US chicken layer flock in {{data_month_long}} in expansion, contraction, or steady?
Options: `expansion` / `contraction` / `steady`
Explanation: Use each month's latest known level: `layers_revised_klb` when it is
filled, otherwise `layers_klb`. Find the row whose `period_label` is
the same month one year before the latest row, and compute the signed
YoY percentage change,

    yoy_pct = (latest level - prior-year level) / prior-year level * 100

and classify it with a +/-0.5% deadband around zero:

- `yoy_pct >  +0.5` -> `expansion`
- `yoy_pct <  -0.5` -> `contraction`
- otherwise (-0.5 <= yoy_pct <= +0.5) -> `steady`

Q2: Wrap up with a 1–3 sentence factual summary covering the current period, the `layer_flock_yoy_phase` tag, and the YoY percentage change you computed.
Options: free text, at most 800 characters.
