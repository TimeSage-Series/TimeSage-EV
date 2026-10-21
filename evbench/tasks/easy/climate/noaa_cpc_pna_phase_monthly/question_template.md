It's now {{month_label_long}}. I need a brief on this release:

Q1: What is the PNA phase for this month?
Options: `positive_phase` / `negative_phase` / `neutral`
Explanation: CPC labels each month's PNA phase by a +/-0.5 sigma threshold on the
standardised PNA index:

- `pna_value >= +0.5` -> `positive_phase`
- `pna_value <= -0.5` -> `negative_phase`
- otherwise -> `neutral`

Q2: Wrap up with a 1–3 sentence factual summary covering the current period, the `pna_phase` tag, and at least one supporting numeric value from the latest CSV row.
Options: free text, at most 800 characters.
