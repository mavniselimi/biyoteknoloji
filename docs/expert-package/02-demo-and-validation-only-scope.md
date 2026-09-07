# 2. DEMO and VALIDATION only

## The two permitted modes

The candidate release manifest names them and names what is forbidden:

```json
"permitted_modes":  ["DEMO", "VALIDATION"],
"prohibited_modes": ["PILOT"]
```

`DEMO` is a person driving the interface to see what the software does.
`VALIDATION` is the benchmark harness running catalogued cases against the
release. `PILOT` — any use where a real clinical decision is downstream of the
output — is refused by the release, not by policy alone.

## Why the candidate release is separate from the governed one

This repository has two release paths, and they are different code.

The **governed** path (WP-13) registers a release in a registry, writes an
active-release pointer, and requires a data-quality decision that permits the
transition. The candidate release has none of that. It is not registered, the
governed active-release pointer does not exist, and it was not written.

The **candidate** path exists because the scientific work needed somewhere to
live that could not be mistaken for the governed one. It is selected by an
explicit runtime track:

```
PGX_RUNTIME_TRACK=CANDIDATE   # or GOVERNED
```

There is no fallback. An unset or unrecognised value fails closed rather than
defaulting to the candidate track, and the composed application asserts which
track it is on before it hands out a service — a component built for one track
cannot be obtained on the other.

## Why the data-quality decision says `ACCEPTED_FOR_CANDIDATE_USE`

The dataset's ordinary quality gate **fails**. Two blocking findings:
`SNAPSHOT_COMPLETENESS_UNKNOWN` and `SOURCE_POLICY_NOT_APPROVED`.

A separate, explicit decision — `DQD-2710a01c386e9a1885f62a8e` —
accepted that dataset **for candidate use only**, naming the blocking issues
it accepted over. That decision keeps `permits_transition = false`.

Those two facts belong together and neither cancels the other. Candidate
acceptance is a decision to proceed with demonstration and validation on a
dataset whose gate did not pass. It is not publication approval, and nothing
in Waves 4, 4B or 5 converted it into one.

## What the modes mean for your review

You are being asked to criticise a build that is allowed to be shown and
measured, and is not allowed to be used. If your conclusion is that it should
not be shown either, that is a valid conclusion and section 16 has a place to
record it.
