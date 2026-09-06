# H02 - curation protocol: what has to be decided

`config/curation/protocol-v1.json` says of itself that it is not scientifically approved and that every vocabulary in it is draft until a named scientist records an approval against its content hash. Its `approval` field is null. Until that changes, every curation work item in the repository stays `RAW`, and it is right that they do.

## What approving this protocol means

It means a person with the standing to do so says: this is how a curator turns a source statement into a curated interpretation in this project, these are the fields, these are the vocabularies, and a conclusion reached this way is one I would defend. It is not a formality and it is not a document review.

## Five things the protocol does not currently address

WP-C04's reading of the primary sources turned up five places where the sources do not fit the shape the project has described. None is a defect in the protocol; each is a question the protocol is silent on, and a curator who meets one mid-task will invent an answer if nobody has given one.

They are set out in `unresolved-questions.md` and carried as decisions `H02-D03` through `H02-D07`.

## The H01 approval is not an H02 approval

A pharmacist has approved this project's source policy. That decision says which sources may be used and on what terms. It says nothing about how a source's content becomes a clinical representation, and it must not be reused here: the reviewer was not asked, and did not answer, any of the questions in this package.

Each row of `proposed-decisions.csv` is bound to the content hash of the protocol and of the legacy disposition report it depends on, so an approval recorded here cannot later attach to different bytes.

## What must not happen

The 1,559 legacy candidates carry the previous project's own risk levels, phenotype strings and plain-language hints. None of that is evidence, and a curation protocol that permitted a curator to start from a legacy row's wording would launder an unreviewed opinion into a curated interpretation. The protocol should be read with that specific failure in mind.

