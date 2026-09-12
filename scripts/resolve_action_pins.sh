#!/usr/bin/env bash
# Resolve every GitHub Action tag into a commit SHA (WP-24).
#
#     scripts/resolve_action_pins.sh            # report what would change
#     scripts/resolve_action_pins.sh --write    # rewrite the workflows
#
# Why this exists. Every `uses:` in .github/workflows carries the all-zero
# SHA, which is a documented placeholder rather than a fabricated pin: forty
# zeros is not a commit in any git repository, so a workflow that reached one
# fails loudly instead of executing whatever happens to be at a guessed
# address. The environment those workflows were written in had no network, and
# inventing forty hex characters would have produced a pin that looks precise,
# is wrong, and would either fail confusingly or - far worse - resolve to
# something nobody reviewed.
#
# This script turns each placeholder into the real SHA of the tag named in the
# comment beside it, using the GitHub API. It changes nothing else, and it
# refuses to write when a tag cannot be resolved: a partially pinned workflow
# is one where the unpinned entries are the ones nobody notices.
#
# Requires: gh (authenticated) or curl, and network access to api.github.com.

set -euo pipefail

WRITE=0
[ "${1:-}" = "--write" ] && WRITE=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PLACEHOLDER="0000000000000000000000000000000000000000"

resolve() {
    # $1 = owner/repo, $2 = tag. Prints the commit SHA the tag points at.
    local repo="$1" tag="$2" sha=""
    if command -v gh >/dev/null 2>&1; then
        # Annotated tags point at a tag object; dereference to the commit.
        sha="$(gh api "repos/${repo}/git/ref/tags/${tag}" \
                --jq '.object.sha' 2>/dev/null || true)"
        local kind
        kind="$(gh api "repos/${repo}/git/ref/tags/${tag}" \
                --jq '.object.type' 2>/dev/null || true)"
        if [ "$kind" = "tag" ] && [ -n "$sha" ]; then
            sha="$(gh api "repos/${repo}/git/tags/${sha}" \
                    --jq '.object.sha' 2>/dev/null || true)"
        fi
    else
        sha="$(curl -fsSL \
            "https://api.github.com/repos/${repo}/commits/${tag}" \
            | sed -n 's/^  "sha": "\([0-9a-f]\{40\}\)".*/\1/p' | head -1)"
    fi
    printf '%s' "$sha"
}

failed=0
changes=0
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

for workflow in .github/workflows/*.yml; do
    cp "$workflow" "$tmp/$(basename "$workflow")"
    # Each line looks like:  uses: owner/repo@<sha> # v1.2.3 - UNRESOLVED
    while IFS= read -r line; do
        case "$line" in
            *uses:*@${PLACEHOLDER}*) ;;
            *) continue ;;
        esac
        repo="$(printf '%s' "$line" | sed -n 's/.*uses:[[:space:]]*\([^@]*\)@.*/\1/p')"
        tag="$(printf '%s' "$line" | sed -n 's/.*#[[:space:]]*\(v[0-9][^ ]*\).*/\1/p')"
        if [ -z "$repo" ] || [ -z "$tag" ]; then
            echo "cannot parse: $line" >&2
            failed=1
            continue
        fi
        sha="$(resolve "$repo" "$tag")"
        if [ -z "$sha" ]; then
            echo "UNRESOLVED  ${repo}@${tag}" >&2
            failed=1
            continue
        fi
        echo "resolved    ${repo}@${tag} -> ${sha}"
        changes=$((changes + 1))
        sed -i.bak \
            -e "s|${repo}@${PLACEHOLDER}|${repo}@${sha}|g" \
            -e '/uses:/ s| - UNRESOLVED$||' \
            "$tmp/$(basename "$workflow")"
        rm -f "$tmp/$(basename "$workflow").bak"
    done < "$workflow"
done

if [ "$failed" -ne 0 ]; then
    echo "" >&2
    echo "Refusing to write: at least one tag could not be resolved." >&2
    echo "A partially pinned workflow is one where the unpinned entries are" >&2
    echo "the ones nobody notices." >&2
    exit 1
fi

if [ "$WRITE" -eq 1 ]; then
    for workflow in .github/workflows/*.yml; do
        cp "$tmp/$(basename "$workflow")" "$workflow"
    done
    echo ""
    echo "Rewrote ${changes} pin(s). Review the diff before committing:"
    echo "  git diff .github/workflows"
else
    echo ""
    echo "${changes} pin(s) would be rewritten. Re-run with --write."
fi
