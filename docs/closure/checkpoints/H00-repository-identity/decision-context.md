# H00 - repository identity: what has to be decided

Before WP-C00 this repository had no commit, no tag, no configured author and no version anything could reference. A release bundle cannot name a software version that does not exist, so the first thing the closure needed was a starting point that could be pointed at. That now exists. What it does not yet have is anybody's confirmation that it is the right one.

## What was created

| Field | Value |
| --- | --- |
| Baseline commit | `f95b467320b9dcab787b4abed76544ffc7ef3641` |
| Tree | `39581eab87e4c75f4a70e4cbab88294ab0139d76` |
| Tag | `baseline/pre-closure-v0.2.0.dev0` |
| Files | 1370 |
| Author | Abdülkadir |
| Remotes | 0 |

The commit was built from an explicit list of paths, never from `git add .`, and the staged set was scanned for secrets and for absolute paths before it was written.

## Why an identity is a decision

An author identity on a commit is a claim about who made it, and it is written into the object hash. Changing it later means rewriting history. The identity used here was supplied for this wave; whether it is the identity this project should carry is not something a maintainer should assume.

## Why publication is a separate decision

The tree contains a quarantined legacy dataset and material acquired before any source policy existed. Where such a repository may be published is exactly the sort of question that should be asked before the first push rather than after it. No remote is configured and nothing has been pushed.

