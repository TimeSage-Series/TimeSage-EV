# Task

You are a tropical-meteorology analyst tracking the Madden-Julian
Oscillation (MJO) over a stretch of consecutive ISO weeks. The MJO is
a 30-60 day eastward-propagating mode of tropical convection and
circulation; NOAA's real-time OLR-based MJO index (ROMI) projects
the daily state onto two principal components that, after the
canonical Wheeler-Hendon sign/order convention (RMM1, RMM2), trace
out a circular phase wheel divided into eight phases (each phase
corresponds to the geographic centre of MJO convective activity).
When the amplitude `sqrt(RMM1^2 + RMM2^2) < 1` the MJO is considered
"weak" (no coherent eastward propagation). Each ISO week you read the
latest Friday sample and label its phase.

# Input

`timeseries.csv` in your working directory is the cumulative weekly Friday-sampled
Wheeler-Hendon RMM history, ascending in time, one row per ISO
week.
Columns:

- `observation_date` -- the sampled trading-day date (YYYY-MM-DD).
  Friday of the ISO week, or the most recent prior day in the same
  ISO week if Friday is missing in the source.
- `iso_week` -- ISO week label, in `YYYY-Www` form.
- `rmm1` -- the canonical Wheeler-Hendon RMM1 value.
- `rmm2` -- the canonical Wheeler-Hendon RMM2 value.
