# Jury demonstration runbook

**Read this first.** The candidate scientific build is complete and executable,
and the browser surface is **not** yet wired to it. That gap is real, measured,
and stated here rather than discovered during a demonstration. What follows
tells you what can be shown today, what cannot, and exactly why.

Nothing in this project is externally reviewed, clinically validated,
independently validated, expert approved or production approved.

## 1. What can be demonstrated today

### 1a. The scientific build, from the command line

This is the substance of the project and it runs end to end:

```
python3 scripts/build_wave03b_manifest.py       # the G1-G10 gate, computed
python3 scripts/run_wave04_benchmark.py         # 55 cases (already run; refuses to re-run)
python3 scripts/run_wave04_performance.py       # 1,000 assessments
```

To show one assessment and its refusals:

```python
from pgx.application.candidate_assessment_service import CandidateAssessmentService
from pgx.application.assessment_models import AssessmentInput
from pgx.domain.claims import OperationMode, PermittedInputKind
from pgx.domain.enums import Phenotype
from pgx.engine.phenotype_models import PhenotypeObservation, PhenotypeProfile

service = CandidateAssessmentService(repo_root=".")

def ask(medications, care_setting=None, **genes):
    profile = PhenotypeProfile(
        observations=tuple(
            PhenotypeObservation(gene_canonical_key="GENE:" + g,
                                 status="NORMALIZED", phenotype=p)
            for g, p in sorted(genes.items())),
        input_contract_version="demo/1")
    return service.execute(AssessmentInput(
        mode=OperationMode.DEMO,
        input_kind=PermittedInputKind.SYNTHETIC_PHENOTYPE_PROFILE,
        profile=profile, medications=tuple(medications),
        care_setting=care_setting))
```

Four demonstrations worth doing, in this order:

| # | Call | What it shows |
|---|---|---|
| 1 | `ask(["DRUG:clopidogrel"], CYP2C19=Phenotype.POOR)` | refuses: `CARE_SETTING_NOT_DECLARED`. The system will not guess which column of the guideline applies. |
| 2 | `ask(["DRUG:clopidogrel"], care_setting="ACS_OR_PCI", CYP2C19=Phenotype.POOR)` | answers `HIGH`, with the rule, the interpretation and the citation attached. |
| 3 | `ask(["DRUG:amitriptyline"], CYP2C19=Phenotype.NORMAL)` | refuses: `PHENOTYPE_NOT_PROVIDED`. A two-gene decision is not answered from one gene. |
| 4 | `ask(["DRUG:codeine"], CYP2D6=Phenotype.RAPID)` | refuses: `PHENOTYPE_NOT_SUPPORTED`. CPIC's CYP2D6 model has no rapid band, so the release does not invent one. |

Each result carries `claim_boundary_is_approved: False` and
`review_state: PENDING_EXTERNAL_EXPERT_REVIEW`.

### 1b. The browser surface, as far as it goes

Start it (needs the `web` extra, which the repository host does not have — see
section 3):

```
uvicorn apps.web.main:app --host 127.0.0.1 --port 8010
```

Then open `http://127.0.0.1:8010`. Three pages render fully:

| Page | What it shows |
|---|---|
| `/` | the landing page and the canonical clinical warning |
| `/login` | the authentication form |
| `/system` | **the most useful page for a jury**: every readiness component, its blocking status, and a sentence saying why |

`/system` is worth dwelling on. It reports `active_release`,
`authentication`, `claim_boundary`, `database`, `evidence_build`,
`governed_audit`, `migrations`, `password_hashing`, `rate_limiter`,
`service_composition` and `session_store`, each with an explanation. Its
claim-boundary row reads: *"The claim boundary has not been approved by the
named human and scientific reviewers. This is a governance gate, not a
fault."* That is the project describing its own state accurately, which is the
thing worth showing.

Screenshots of all nine states, captured through Chromium at 1440×900, are in
`data/web/wave-04-browser/`.

## 2. What cannot be demonstrated, and why

**The authenticated pages.** `/cases`, `/validation`, `/assessments/{id}`,
`/evidence/{id}` and `/expert-reviews/{id}` all return **503
`AUTHENTICATION_NOT_CONFIGURED`**. This is not a bug and not a missing feature:
the deployment has no authentication provider, because composing one needs a
database session store, which needs a PostgreSQL driver, which cannot be
installed on either available host. The page says so, in those words, and
refuses to show a partial result.

**The web surface is not wired to the candidate release.** `/system` reports
`active_release: No active release is registered`, and it is right to: the web
provider reads the *governed* active-release pointer, and the candidate release
lives on its own pointer. Wiring the two is remaining work, not a defect in
what exists.

**Therefore the full six-screen jury flow — Case Input → Assessment → Finding
Detail → Validation Dashboard → Expert Review → System Information — cannot be
walked in a browser today.** Four of its six screens are behind
authentication. This is stated plainly because a demonstrator should not
discover it live.

## 3. Preparing the environment

The repository host has `jinja2` and nothing else from the web stack. To serve
the interface you need a machine with network access and:

```
pip install fastapi uvicorn starlette pydantic jinja2 python-multipart
```

`sqlalchemy`, `alembic` and `psycopg` are additionally needed before any
authenticated page will work.

Once the server is running, sections 1a and 1b need **no terminal commands
beyond starting it** — which is the acceptance criterion WP-C14A sets, met for
the surface that exists and unmet for the surface that does not.

## 4. What to say about status

Accurate:

> A complete candidate prototype. Source-grounded, internally validated,
> project-team provisional, pending external expert review.

Not accurate, and not to be said:

> clinically validated · independently validated · expert approved ·
> production approved · THS-6 complete
