It's now {{period_long}}. I need a brief on this release:

Q1: Compared with the same ISO week in 2019, which recovery band does TSA checkpoint throughput fall into this week?
Options: `well_below` / `still_below` / `approaching` / `recovered`
Explanation: Compute the latest row's recovery ratio,

    recovery = throughput / baseline_2019

and classify it with a fixed 4-way cascade:

- `recovery < 0.75` -> `well_below`
- `0.75 <= recovery < 0.95` -> `still_below`
- `0.95 <= recovery < 1.05` -> `approaching`
- `recovery >= 1.05` -> `recovered`

Q2: Wrap up with a 1–3 sentence factual summary covering the current period, the `recovery_band` tag, and at least one supporting numeric value from the latest CSV row.
Options: free text, at most 800 characters.
