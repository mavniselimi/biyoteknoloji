# Consent and data handling

Read this before you write anything you would not want published.

## What is stored

Your name, your professional qualification, your affiliation, your declared
conflicts, your answers, and your signature line — as text, in the project's
git repository, in `data/expert-review/` and `data/closure/`.

## Where it goes

Into git. That means:

- it is **public** if the repository is public, and it is intended to become
  so, because a review that nobody can read is not evidence of review;
- it is **permanent** in the sense that git history retains it. A later commit
  can remove a file; it does not remove the earlier commit that contained it;
- it is **byte-preserved**. Your response is stored verbatim and hashed. The
  project may not paraphrase it into the record.

If any of that is unacceptable, do not submit under your name. A pseudonymous
or withheld-identity review is still useful; it simply cannot be described as
attributable, and the record will say so.

## What is not involved

**No patient data.** None has ever been in this system. The validation cases
carry gene symbols, drug names, phenotype labels and a care setting from a
closed vocabulary — no identifier, no date of birth, no free text about any
person. You will not be handling health data and you are not being asked to
act as a data processor.

## What the project may do with your review

- Store it, publish it, and cite it as *"an external scientific review by
  \<name\>, \<qualification\>, dated \<date\>"*.
- Extract discrete feedback items from it, each linked back to the exact text
  it came from.
- Act on it, or record a reasoned disagreement with it.

## What the project may not do

- Describe it as approval, validation, endorsement or sign-off.
- Describe you as having approved anything you did not.
- Edit it. Corrections are appended with their own timestamp and author.
- Extend it beyond what you wrote — an answer about one axis is about that
  axis.
- Cite it after you withdraw.

## Withdrawal

Say so, in writing, to the project owner. The project will record the
withdrawal, stop citing the review, and remove the response file in a new
commit. It will not claim to have erased git history, because it cannot.

## Retention

Indefinite, in git, for as long as the repository exists. There is no
retention period that a git repository can honestly promise, so none is
offered.

---

**Consent**

> - I understand my review will be stored in this project's git repository and
>   is intended to be published. ☐
> - I understand no patient data is involved. ☐
> - I consent to my name being recorded and cited as described above. ☐
>   (If not, write `PSEUDONYMOUS` or `WITHHELD` and the review will be
>   recorded that way.)
>
> Name: ____________________  Date: ____________
