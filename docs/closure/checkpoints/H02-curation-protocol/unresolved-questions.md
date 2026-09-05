# H02 - unresolved questions

These came out of reading the primary sources for the five declared axes. Each is a place where the source's own structure and the project's declared scope do not line up. None of them can be settled by looking at the repository, because the repository is what encodes the assumption in question.

## Where the sources and the declared scope disagree

### SC-01 - amitriptyline is one two-gene decision, not two axes

- **What the sources say:** CPIC's amitriptyline recommendations are keyed by a CYP2D6 and CYP2C19 pair together; every recommendation record carries both gene keys. The project's scope names CYP2C19::amitriptyline and CYP2D6::amitriptyline as two independent axes.
- **Why it matters:** A rule that answers for one gene while the source answered for both is not a subset of the source's recommendation; it is a different claim. Splitting the matrix is a scientific decision.
- **The decision:** Whether the first release models amitriptyline as a two-gene matrix, restricts itself to the single-gene cells the source states separately, or removes amitriptyline from the first release.
- **Owner:** clinical pharmacogenomics reviewer

### SC-02 - clopidogrel recommendations depend on indication

- **What the sources say:** CPIC states clopidogrel recommendations separately for cardiovascular indications with acute coronary syndrome and percutaneous coronary intervention, for other cardiovascular indications, and for neurovascular indications. The project's scope has no indication axis.
- **Why it matters:** Collapsing three population-specific recommendations into one loses the condition each was stated under. Presenting the strongest of them as the answer would overstate the source.
- **The decision:** Whether the first release carries an indication axis, restricts itself to one indication and says so, or defers clopidogrel.
- **Owner:** clinical pharmacogenomics reviewer

### SC-03 - the five-phenotype vocabulary does not fit CYP2D6

- **What the sources say:** CPIC does not assign a RAPID phenotype for CYP2D6, and it does emit Likely Poor, Likely Intermediate and Indeterminate, none of which the project's five-value vocabulary can express. CYP2D6 recommendations are keyed by activity score, not by a phenotype label alone.
- **Why it matters:** A vocabulary that cannot represent what the source said will either drop cases silently or map them to a neighbouring value. Both are misrepresentation.
- **The decision:** Whether the phenotype vocabulary is extended, whether unrepresentable phenotypes are refused explicitly, and whether CYP2D6 carries an activity score.
- **Owner:** clinical pharmacogenomics reviewer

### SC-04 - the FDA does not cover one declared axis

- **What the sources say:** FDA labelling addresses four of the five declared axes. CYP2C19 with amitriptyline is absent. Of those it does address, only clopidogrel and codeine carry boxed-warning-strength language.
- **Why it matters:** A design that expects a regulator statement for every axis will find none for this one, and a reader who sees four covered may assume the fifth is too.
- **The decision:** Whether an axis without regulator labelling may still be released, and how its absence is shown.
- **Owner:** clinical pharmacogenomics reviewer

### SC-05 - the clopidogrel boxed warning no longer says 'poor metabolizer'

- **What the sources say:** The current clopidogrel boxed warning is worded around carrying two loss-of-function alleles of CYP2C19 rather than around the phenotype term.
- **Why it matters:** Any extraction keyed on the phrase 'poor metabolizer' will silently return nothing for the single most important warning in the first release, and silence looks the same as absence.
- **The decision:** How label extraction is keyed, and how a zero-result extraction is distinguished from a genuine absence.
- **Owner:** clinical pharmacogenomics reviewer


