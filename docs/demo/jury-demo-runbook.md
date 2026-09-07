# Jury demonstration runbook

**Read this first.** The candidate scientific build is complete and
executable, and since Wave 4B the browser surface reaches it. The full
six-screen flow — Case Input → Assessment → Finding Detail / Evidence →
Validation Dashboard → Expert Review → System / Release Information — can be
walked by a person clicking links.

Nothing in this project is externally reviewed, clinically validated,
independently validated, expert approved or production approved. Section 5
says what may and may not be said about it.

## 1. Starting the demonstration

Six commands, from the repository root. Nothing after step 6 requires a
terminal.

**1. Start the project's PostgreSQL.** The compose default is host port
**55433**, not 5432 — a native PostgreSQL on this Mac already listens on 5432,
and a container published there is shadowed by it. Every connection reaches the
other server, which answers and then refuses a role it has never heard of:
`FATAL: role "pgx_dev" does not exist`.

```
docker compose up -d postgres
```

Override with `POSTGRES_HOST_PORT=<port>` if 55433 is taken. Nothing else on
the machine is stopped, reset or deleted, and the named volume is preserved.

**2. Point the environment at it.**

```
export DATABASE_URL="postgresql+psycopg://pgx_dev:pgx_dev_password@127.0.0.1:55433/pgx_dev"
export PGX_RUNTIME_TRACK=CANDIDATE
export PGX_API_ENV=DEVELOPMENT
export PGX_API_AUTH_MODE=SESSION
export PGX_API_MIGRATION_HEAD=0012_wave03b_candidate_capture
export PGX_CANDIDATE_REPO_ROOT="$PWD"
```

`PGX_RUNTIME_TRACK` has no default and no fallback. Unset or unrecognised
fails closed rather than quietly selecting a track.

**3. Migrate.** The ordinary online alembic path over psycopg, not SQL text:

```
alembic upgrade 0012_wave03b_candidate_capture
```

**4. Create the demonstration account.** A strong password is generated and
written **only** to the file named below, mode 0600. It is not printed, not
logged and not committed. No ADMIN account is created; the flag that would
permit one is not passed.

```
python3 scripts/bootstrap_demo_environment.py setup \
    --user jury:DEMO_USER \
    --credentials-out /private/tmp/pgx-demo-credentials.txt
```

If `jury` already exists the script leaves it alone and says so — it does not
overwrite an account and does not weaken the password store. Create a second
named account instead:

```
python3 scripts/bootstrap_demo_environment.py setup \
    --user jury2:DEMO_USER \
    --credentials-out /private/tmp/pgx-demo-credentials.txt
```

**5. Check readiness.** JSON, no secrets. It must print `"ready": true`; if it
does not, it names the blockers.

```
python3 scripts/bootstrap_demo_environment.py check
```

It verifies: the database is reachable, the migration head is correct, at
least one demo account exists, every required capability is composed, and the
candidate release resolves.

**6. Serve it.**

```
uvicorn apps.web.main:app --host 127.0.0.1 --port 8010
```

Open `http://127.0.0.1:8010` and sign in as `jury` with the password from
`/private/tmp/pgx-demo-credentials.txt`.

**Use one hostname for the whole session.** `127.0.0.1` and `localhost` are
different origins to the cookie, and switching mid-session loses it.

## 2. The walk

Navigate by **clicking links in the page**. The session cookie is
`__Host-pgx_session` with `SameSite=Strict`, so a URL typed into the address
bar during an authenticated session may arrive without it and answer 401.
A person clicking is unaffected; this note is here so that an unexpected 401
is not read as a fault.

| # | Do this | What it shows |
|---|---|---|
| 1 | land on `/` before signing in | the canonical clinical warning, on this and every other page |
| 2 | click through to a guarded page | **401**, cleanly, with no stack trace |
| 3 | sign in with the wrong password | refused |
| 4 | sign in properly | session established |
| 5 | open the case catalogue | seven development cases, labelled as demonstration data |
| 6 | open a case | four candidate drugs and the care-setting control |
| 7 | assess clopidogrel with **no** care setting | **`CARE_SETTING_NOT_DECLARED`** — the system will not guess which column of the guideline applies |
| 8 | assess clopidogrel in `ACS_OR_PCI` | answered, with the release, ruleset, matched rule, citation and capture records |
| 9 | assess amitriptyline on a case with both genes | answered from the **joint** twelve-cell table |
| 10 | assess amitriptyline on a case missing one | **`PHENOTYPE_NOT_PROVIDED`** — a two-gene decision is not answered from one gene |
| 11 | open the validation dashboard | `INTERNAL_VALIDATION`, partition counts, and the one-author limitation stated |
| 12 | open system / release | candidate and governed tracks, **separately** |
| 13 | sign out, then try a guarded page | **401**; the server-side session is revoked, not just the cookie |

Steps 7, 10 and 13 are the ones worth dwelling on. A refusal is not a finding
of low risk — the interface shows coverage and attention as a labelled pair,
and a refused medication reads `NOT_ASSESSED`, never an attention level.

## 3. Showing the science without a browser

Useful when the projector is a terminal.

```
python3 scripts/build_wave03b_manifest.py    # the G1-G10 gate, computed
python3 scripts/build_wave04b_manifest.py    # WP-C14A and WP-C14, computed
python3 scripts/build_wave05_artifacts.py    # the expert package, rebuilt
```

One assessment and its refusals, in-process:

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

| # | Call | What it shows |
|---|---|---|
| 1 | `ask(["DRUG:clopidogrel"], CYP2C19=Phenotype.POOR)` | refuses: `CARE_SETTING_NOT_DECLARED` |
| 2 | `ask(["DRUG:clopidogrel"], care_setting="ACS_OR_PCI", CYP2C19=Phenotype.POOR)` | answers `HIGH`, with rule, interpretation and citation |
| 3 | `ask(["DRUG:amitriptyline"], CYP2C19=Phenotype.NORMAL)` | refuses: `PHENOTYPE_NOT_PROVIDED` |
| 4 | `ask(["DRUG:codeine"], CYP2D6=Phenotype.RAPID)` | refuses: `PHENOTYPE_NOT_SUPPORTED` — CPIC's CYP2D6 model has no rapid band, so the release does not invent one |

Every result carries `claim_boundary_is_approved: False` and
`review_state: PENDING_EXTERNAL_EXPERT_REVIEW`.

## 4. What still cannot be shown

- **Any external review.** Nobody outside this project has reviewed anything.
  The expert package is prepared and unsent: `docs/expert-package/README.md`.
- **The twelve reserved cases.** Sealed, unopened, and carrying no expected
  answers. They are questions for a reviewer, not a test the software passes.
- **A governed release.** The candidate release is not registered in the WP-13
  registry and the governed active-release pointer does not exist.
- **A passing data-quality gate.** It fails on
  `SNAPSHOT_COMPLETENESS_UNKNOWN` and `SOURCE_POLICY_NOT_APPROVED`; a separate
  decision accepted the dataset for candidate use over both and keeps
  `permits_transition = false`.
- **Staging, load testing, backup/restore, SBOM or vulnerability scanning.**
  None has been executed; each is recorded as blocked with a measured reason.
- **THS-6.** Not closed. `ths6_achieved: false`, `release_may_proceed: false`,
  no gate passing, Definition of Done at 1 of 15.

## 5. What to say about status

Accurate:

> A complete candidate project. Source-grounded, project-team provisional,
> internally validated, pending external expert review.

Not accurate, and not to be said:

> clinically validated · independently validated · expert approved ·
> production approved · THS-6 complete · externally reviewed

If asked "has a pharmacist looked at this?" — one has, at the **source
policy** only, on 6 September 2026, and that attestation explicitly does not
cover any generated rule. Say that, rather than yes.
