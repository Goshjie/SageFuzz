# Experiment Records

This directory stores hand-curated experiment manifests that group multiple run
artifacts under a stable experiment label.

Naming convention:

- `<YYYY-MM-DD>__<model-id>.json`
- `<YYYY-MM-DD>__<model-id>.md`

Each record should capture:

- model id and provider endpoint
- experiment date
- the run/index paths used as evidence
- whether token accounting was available
- a short judgment about testcase intent alignment

Raw generation artifacts still live under `runs/`. The files here are the
cross-run registry used to compare different models on different dates.
