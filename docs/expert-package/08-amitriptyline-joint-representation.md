# 8. Amitriptyline as one joint CYP2C19+CYP2D6 decision

## The decision

Amitriptyline is modelled as **one joint rule family over both genes**, not as
two independent single-gene axes whose answers are combined afterwards. It is
the only joint family in the release: `is_joint = true`, condition kind
`PGX_JOINT_AXIS`, axis key
`GENE:CYP2C19+GENE:CYP2D6|DRUG:amitriptyline`.

This was a preserved owner decision recorded in the H01 file before any rule
was written: amitriptyline *"must be modelled as a scientifically reviewed
joint CYP2C19 and CYP2D6 decision, not two falsely independent axes"*.

## The twelve cells

| CYP2C19 | CYP2D6 | Attention |
|---|---|---|
| RAPID or ULTRARAPID | POOR or ULTRARAPID | HIGH |
| RAPID or ULTRARAPID | INTERMEDIATE or NORMAL | HIGH |
| NORMAL | ULTRARAPID | HIGH |
| NORMAL | POOR | HIGH |
| NORMAL | INTERMEDIATE | MEDIUM |
| NORMAL | NORMAL | NO_ACTIVE_ATTENTION |
| INTERMEDIATE | ULTRARAPID | HIGH |
| INTERMEDIATE | POOR | HIGH |
| INTERMEDIATE | INTERMEDIATE | MEDIUM |
| INTERMEDIATE | NORMAL | NO_ACTIVE_ATTENTION |
| POOR | POOR, INTERMEDIATE or ULTRARAPID | HIGH |
| POOR | NORMAL | HIGH |

Rule keys `CANDIDATE-RULE:amitriptyline|JOINT|01` … `|12`. The cells are
mutually exclusive; no observation matches two.

## Why joint matters, mechanically

Because the joint answer is not the maximum of two single-gene answers. Take
CYP2C19 NORMAL with CYP2D6 INTERMEDIATE: `MEDIUM`. Take CYP2C19 POOR with
CYP2D6 NORMAL: `HIGH` — even though CYP2D6 NORMAL would contribute nothing on
its own. A max-of-two-axes implementation would produce a different table, and
the reserved case `PGX-VAL-W4-EXP-09` was written specifically to put a cell
where the two approaches diverge in front of a reviewer.

## The refusal that follows from it

A joint rule needs **both** genes. If either is missing, the axis returns
`INSUFFICIENT` / `PHENOTYPE_NOT_PROVIDED` with the detail *"Every gene a joint
rule names must be present; the release does not answer from the axis that
was."*

So amitriptyline with only CYP2D6 observed is refused, even though a CYP2D6
answer exists for codeine in the same request. That is deliberate: answering
from the half that was observed would present a single-gene reading as if it
were the joint one.

## What to criticise

- **Are the twelve cells right?** They are the compression of a guideline
  table into five attention levels by an automated pass. Cell by cell.
- **Is `POOR`/`NORMAL` → `HIGH` right**, and is `NORMAL`/`INTERMEDIATE` →
  `MEDIUM` right?
- **Is refusing on one missing gene right**, or should the product say
  something useful about the gene it does have, clearly labelled as partial?
- **Is the joint answer legible?** In the interface a joint result and a
  single-gene result sit side by side. Reserved case `EXP-09` asks whether a
  clinician can tell which is which.

Question **Q06** in section 16.
