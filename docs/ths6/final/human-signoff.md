# Human sign-off matrix

**Nine roles. Zero signed. No mechanism to sign.**

There is deliberately no command, flag, fixture or test helper in this
repository that can record a signature. Signing is a human act performed
outside this software, and a repository that could manufacture one would have
made the signature worthless. `signature_mechanism` is `null` in the artifact
and the schema requires it to be.

There are **no example names**. `signatory` is `null` in every row and the
schema pins it to null. A placeholder like "Dr A. Example" in a governance
document survives a copy-paste into a slide, and by then nobody remembers it
was a placeholder.

Each role attests in the first person, because a signature is a personal claim
rather than a passive sentence.

| ID | Role | Attests to | Gate |
|---|---|---|---|
| SIGN-01 | Scientific source approver | *I have reviewed each registered source against the source review checklist and I approve its use as scientific evidence.* | A |
| SIGN-02 | Data owner | *I confirm the canonical dataset is built from a complete, sealed snapshot and that its published identity is immutable.* | A |
| SIGN-03 | Curation lead | *I confirm every interpretation was curated under the approved protocol and that each rule carries complete approval metadata.* | B |
| SIGN-04 | Clinical safety authority | *I approve the claim boundary: what this system may state, what it may not, and the wording of each refusal.* | C |
| SIGN-05 | Validation owner | *I confirm the validation set is adequate for the intended use and that the holdout set was not used in rule development.* | D |
| SIGN-06 | Expert review chair | *I confirm the review protocol was approved before review began and that each recorded review was performed blind-first.* | D |
| SIGN-07 | Security owner | *I confirm authentication, authorisation and the audit trail were exercised against real governed stores and that the chain verifies.* | E |
| SIGN-08 | Platform owner | *I confirm the staging deployment, its health checks, its backup and restore, and its reliability drills were executed and observed.* | E |
| SIGN-09 | Release approver | *I authorise this release: I have read the evidence pack, I accept its stated limitations, and I accept responsibility for the decision.* | F |

## What each role must have reviewed

Every row names specific artifacts rather than "the evidence". A sign-off
against an unnamed body of material is one nobody can audit afterwards. The
full list is in `data/ths6/wp25-signoff-matrix.json`.

## Sign-off is one of four conditions of achievement

`ths6_achieved` is the conjunction of: all gates pass, all fifteen Definition
of Done items satisfied, the representative demonstration executed, and all
nine sign-off roles signed.

The fourth is there on purpose. A programme whose gates all passed and whose
demonstration ran, with nobody willing to put their name to it, has not
achieved a standard that exists to record human accountability.

## Order

Sign-offs come last, not first. Each role's attestation refers to work that
has not been done: there is no approved source for SIGN-01 to approve, no
published dataset for SIGN-02, no curated interpretation for SIGN-03. Asking
for a signature now would be asking somebody to attest to an absence.
