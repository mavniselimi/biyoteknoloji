# Contingency plan

Fourteen scenarios. Each has a detection signal, a response, what the response
proves, and — the field that makes this document honest rather than
reassuring — **what it does not prove**.

That last field exists because a contingency matrix is where a project's
overstatement usually collects. "If the database is unavailable, show the
cached result" reads as resilience. It is resilience about availability and
silence about correctness, and a viewer watching the fallback has no way to
tell which they are being shown.

Seven scenarios permit continuing. Seven require stopping.

## Continuation permitted

| ID | Scenario | Response | Does not prove |
|---|---|---|---|
| CONT-01 | No network at the venue | continue; the demo is specified to run offline | anything about the correctness of what is displayed |
| CONT-02 | Projector fails | continue on the operator's screen | that a run seen by fewer people is a different run |
| CONT-03 | Stylesheet or font fails to load | continue; the interface names the missing assets | anything about the science; a stylesheet is not a finding |
| CONT-09 | The assessment produces no findings | show the empty result with its coverage axis | that the case has no pharmacogenomic implication |
| CONT-10 | Audience asks for a real patient case | decline; the case model refuses those fields at any depth | that the system could handle such a case safely if asked |
| CONT-11 | Audience asks about clinical validation | answer that none has been performed, without qualification, and name what is missing | any softened version of the answer |
| CONT-12 | The expert reviewer is unavailable | state that no expert review has been completed at all | that a review would have happened but for the absence |

## Continuation refused

| ID | Scenario | Response | Does not prove |
|---|---|---|---|
| CONT-04 | Database unavailable mid-run | stop; show readiness naming the missing component | that an assessment was computed; nothing was |
| CONT-05 | Container runtime will not start the image | stop; do not substitute a local process described as staging | that a local process is a deployment |
| CONT-06 | No approved dataset available | stop before case selection | that the pipeline works on real data |
| CONT-07 | No executable ruleset registered | stop before assessment | that any rule is correct |
| CONT-08 | A safety invariant fails | stop the whole demonstration immediately | nothing that would justify continuing |
| CONT-13 | The evidence pack fails its own integrity check | stop; do not rebuild the pack to make the check pass | that the underlying evidence was ever different |
| CONT-14 | A gate appears to pass unexpectedly | stop; treat it as a defect, not as good news | that the programme advanced |

## No row substitutes anything

No scenario directs the use of a fixture in place of governed content, a
cached number in place of a computed one, or a local rehearsal in place of a
deployment. Where the honest response is to stop, the row says stop and
`continuation_permitted` is false.

The unit suite checks this two ways: every mention of substituting must be
negated (CONT-05's response is *"do not substitute a local process while
describing it as staging"*, which is the strongest anti-substitution sentence
here), and no response may contain a directive to use a fixture or show a
cached value.

## CONT-14 deserves emphasis

An unexplained `PASS` in this software is far more likely to be a bug than
good news. Every gate in this repository is blocked for reasons rooted in
work nobody has done. If one of them starts passing, the first hypothesis is a
defect in the pack, and the response is to stop and re-derive from source
artifacts.
