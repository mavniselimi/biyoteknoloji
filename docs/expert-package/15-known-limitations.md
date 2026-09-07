# 15. Known scientific, operational and product limitations

Listed rather than summarised. A summary is where a limitation goes to die.

## Scientific

1. **No pharmacogenetics specialist has read any rule.** The rules were built
   by an automated curation pass; the manifest names it in the field a
   curator's name would occupy.
2. **The one human approval covers the source policy only**, and explicitly
   does not cover any generated rule (section 4).
3. **Four drugs, two genes.** Chosen by what one person could capture by hand,
   not by what matters most.
4. **No activity scores, no diplotypes, no copy number.** The software begins
   at the phenotype and neither performs nor checks the assignment.
5. **Attention levels are a five-way compression of guideline recommendation
   text**, performed by that same automated pass, using a mapping that appears
   in no guideline.
6. **`HIGH` covers clinically different situations** — clopidogrel POOR and
   clopidogrel INTERMEDIATE are the same level.
7. **No drug–drug interaction logic.** Two drugs on one gene are reported
   separately with no interaction claim (reserved case `EXP-01`).
8. **Source-conflict handling is implemented and unexercised.** No real
   disagreement between approved sources is currently reachable.
9. **No external identifiers.** Nothing is keyed to RxNorm, ATC or HGNC.
10. **The dataset's quality gate fails** on `SNAPSHOT_COMPLETENESS_UNKNOWN`
    and `SOURCE_POLICY_NOT_APPROVED`; it was accepted for candidate use over
    both.

## Validation

11. **No independent validation exists.** One process wrote the rules, the
    cases and the expectations (section 13).
12. **The reserved partition is empty of answers** and has produced no
    evidence.
13. **`unsafe_false_reassurance_count = 0` is bounded by who chose the 55
    cases.**
14. **Latency figures are in-process** and are not a performance
    characteristic.

## Operational

15. **One environment.** A local representative environment on one machine.
    Not external staging; there has been no staging deployment.
16. **No load, soak or concurrency testing.**
17. **No backup or restore has been executed.** The procedure is documented
    and unexecuted, and the status artifact records all three facts as false
    rather than as a placeholder.
18. **No SBOM and no vulnerability scan.** Neither host has package-index
    egress; the dependencies were built from upstream source. The residuals
    are recorded as blocked with a measured reason, not skipped.
19. **No disaster-recovery drill, no monitoring, no alerting.**
20. **The demonstration ran in the session's Linux container, not on the
    project owner's Mac.** The port-collision fix is in the repository and
    applies there; that machine has not run the demonstration.

## Product

21. **A refusal and a low-attention finding are visually adjacent.** They are
    separate fields and separately labelled, and whether that is enough for a
    hurried reader is question **Q09**.
22. **An irrelevant care setting is ignored rather than refused** (section 9,
    reserved case `EXP-10`).
23. **An observation for a gene the axis does not name is ignored silently**
    (reserved cases `EXP-07`, `EXP-08`).
24. **The highest attention level dominates the summary**, which may hide
    refused drugs beneath an answered one (reserved case `EXP-04`).
25. **Turkish and English are mixed** across the interface and the artifacts.
26. **No accessibility audit** has been performed.
27. **No print or export path.** A clinician cannot take the output anywhere.

## Governance

28. **The candidate release is not registered** in the governed release
    registry, and the governed active-release pointer does not exist.
29. **`permits_transition = false`** on the DQ decision, unchanged.
30. **THS-6 is not closed**, no THS-6 gate was touched, and the final
    evidence pack is explicitly `PRE-EXPERT / NOT FINAL`.

## What is missing from this list

Whatever you find. Question **Q12** asks for it in priority order.
