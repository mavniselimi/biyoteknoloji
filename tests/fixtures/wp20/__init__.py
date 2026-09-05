"""WP-20 negative-control fixtures: deliberately unsafe doubles.

Everything here is wrong on purpose. Each module realises one or more entries
in ``pgx.safety.controls.NEGATIVE_CONTROLS`` and exists to be **rejected** by
the evaluator whose success is being claimed.

Two rules, both load-bearing:

* **In-memory only.** No fixture modifies production source on disk. A mutation
  test that edited a real module would leave the repository broken if it were
  interrupted, and would make the suite's result depend on the order it ran in.
* **Never imported by production code.** ``tests/unit/safety/test_boundaries.py``
  asserts that nothing under ``pgx/`` or ``apps/`` imports this package.

None of these fixtures contains real patient data, a real genotype, or anything
derived from one. The unsafe *shapes* are synthetic: a field named
``patient_name`` carrying the string ``"NEGATIVE-CONTROL"``, not a person.
"""
