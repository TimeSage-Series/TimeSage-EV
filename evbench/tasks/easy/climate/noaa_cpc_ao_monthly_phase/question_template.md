It's now {{month_label_long}}. I need a brief on this release:

Q1: What is the AO phase for this month?
Options: `Positive` / `Negative` / `Neutral`
Explanation: CPC labels each month's AO phase by a ±0.5 sigma threshold on the
standardised AO index:

- `ao_value >= +0.5` → `Positive`
- `ao_value <= -0.5` → `Negative`
- otherwise → `Neutral`

Q2: Wrap up with a 1–3 sentence factual summary covering the current period, the `ao_phase` tag, and at least one supporting numeric value from the latest CSV row.
Options: free text, at most 800 characters.
