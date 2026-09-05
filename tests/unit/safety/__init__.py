"""WP-20 safety-gate tests.

One module per invariant, each proving the same two things:

* the **safe control** passes through the evaluator - so a detector that
  rejected everything would be caught, not mistaken for a working one;
* every **negative control** is rejected by that same evaluator, with the exact
  refusal code the registry declares.

Plus the gate's own tests: the registry fails closed, a missing control blocks,
a detector that accepts its mutant blocks, and zero executed checks can never
be a pass.
"""
