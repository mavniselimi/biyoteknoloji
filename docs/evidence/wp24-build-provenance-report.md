# WP-24 build provenance report

| Field | Value |
|---|---|
| Document ID | `DOC-EVID-024-A` |
| Artifact | `data/deployment/wp24-build-provenance.json` |
| Schema | `schemas/wp24/build-provenance.schema.json` |
| Status | **No image was built. No distribution was built. No lockfile exists.** |

---

## 1. What a provenance document is for

One question: *what exactly was this made from?*

Normally the answer starts with a commit hash. This repository has **no
commits** — `git log` reports an empty `main` and every path is untracked — so
`source_revision` is `null`, and it is `null` rather than `"unknown"` so that a
consumer comparing two provenance documents cannot match them on a placeholder
string.

## 2. What stands in for a commit

A **source-tree manifest hash**: a digest over the relative path and content
hash of every source file, sorted, with a declared exclusion list.

```
source_revision              null
source_tree_manifest_hash    sha256:9b6756da82817af0805227aed833a9fd…
source_tree_file_count       1285
```

It is deterministic by construction — paths are relativised, normalised to
forward slashes and sorted before hashing, so the digest does not depend on
walk order, path separator, or where the checkout lives. Two runs in this
session produced the same value.

It is **not** a commit hash and is not presented as one. It is a content
identity: it says nothing about history, authorship or review.

**Tests are included** in the identity. A provenance that ignored them would
report the same value for a tree whose verification had been deleted.

Excluded: `.git`, both virtualenvs, `_to_delete`, `build`, caches,
`__pycache__`, `*.pyc`.

## 3. The identities that exist

```
pyproject_hash               sha256:b945fc675ee3c4aaf9a47e98847e6eeb…
dockerfile_hash              sha256:8e0b982a356670d890e5823f31c62ae4…
runtime_asset_manifest_hash  sha256:239801e551794f74a9928a8d20fb317d…
python_version               3.11.15   (the deployment pins 3.11)
platform_machine             x86_64
```

The runtime-asset manifest hash covers the eleven declared files and their
checksums only — not `present`, not `matches_pinned`, not any other
observation. So two builds of the same source produce the same manifest hash
even when one host is missing a file, and the missing file is reported
separately where it cannot be mistaken for a different manifest.

## 4. The identities that do not

```
lockfile_hash        null    no uv.lock exists
lockfile_present     false
wheel_sha256         null    no distribution was built
sdist_sha256         null
image_repository     null
image_tag            null
image_digest         null    no image was built
base_image_digest    null    the registry could not be reached
sbom_reference       null
sbom_sha256          null
built_at             null    no build ran
ci_run_id            null    no provider has run anything
```

Every one is `null`, never zero and never a placeholder. An absent image digest
means no image was built; it does not mean an image was built and nobody wrote
the digest down.

## 5. Why each is absent

| Missing | Cause, measured |
|---|---|
| `uv.lock` | `uv lock` exited 1 — `pypi.org/simple` returns **HTTP 403** through this environment's proxy. One attempt was made. No lockfile was written, and none was hand-written: a set of versions no resolver agreed on is not a lockfile. |
| wheel / sdist | `hatchling` is not importable here. The declared PEP 517 backend is the only one that may build this project — substituting `setuptools` would produce a different artifact than any deployment installs. |
| image | `docker` is on `PATH` and `docker info` exits 1: the CLI exists and no daemon answered. A version probe alone would have reported a runtime that is not there. |
| base image digest | pinning by digest requires pulling the image. The Dockerfile pins the tag to the exact patch release and `deploy/base-image.pin` is the documented place a resolved digest goes; it is empty, and the provenance says so rather than guessing. |
| SBOM | no generator installed, and no image or lockfile to describe. An SBOM built from `pyproject.toml` would list what *might* be installed — that file declares ranges. |

## 6. Reproducibility, as far as it was measured

**Provenance:** two runs in this session produced identical identity fields.
`compare_provenance()` excludes `built_at`, `ci_run_id`, `ci_run_url`,
`builder` and `builder_version` — two reproducible builds differ in all of
those and are the same build.

**Distributions:** the double-build comparison is implemented and reports
`BLOCKED`. When it runs, it builds twice from two separate clean staging
directories with `SOURCE_DATE_EPOCH` pinned to `1735689600` and compares
artifact hashes. The epoch is pinned across both runs because a zip archive
records mtimes, and two builds a second apart would otherwise differ in bytes
while being identical in content — reporting irreproducibility that is not
there, and training whoever reads the report to ignore it.

**Images:** `compare_images()` deliberately does **not** treat a digest
difference as irreproducibility. An image digest covers the config and every
layer, and layers carry timestamps, build-arg history and BuildKit
attestations; two builds of identical source routinely differ there while
containing identical filesystems. The comparison is over `layer_diff_ids`,
`user`, `entrypoint`, `command`, `exposed_ports`, `architecture` and `os`, and
the digest comparison is recorded beside it rather than instead of it.

## 7. What this report does not establish

It does not establish that an image exists, that anything was installed from a
verified lockfile, that a scanner examined anything, or that any of this was
built on a machine other than the one that produced the numbers above.

It establishes what the build *would* be made from, and it names every identity
it does not have.
