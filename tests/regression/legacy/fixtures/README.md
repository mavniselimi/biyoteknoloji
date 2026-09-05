# WP-01 frozen legacy regression fixtures

These files are **frozen legacy evidence**, captured by
`scripts/build_legacy_baseline.py` from offline reruns of the legacy scripts.

They reproduce legacy behaviour **including known defects** and exist so that a
future V2 difference can be recognised and classified. They are:

- **not** clinical validation,
- **not** scientifically approved,
- **not** protected expected results.

Every value here is covered by the `LEGACY-BUG-*` registry in
`data/legacy-baseline/expected-differences.json`, where every entry carries
`protected_as_correct: false`.
