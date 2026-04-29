# Runbook: Ownership Accountability Weak

## Symptom
`check_owner_tag.py` reports commits without `Owner: <track>` trailer or `[<track>-W<n>-<id>]` subject prefix.

## Cause
Developer forgot to include ownership tracking in commit message.

## Resolution
1. Amend the commit (if not yet pushed): `git commit --amend` to add `Owner: CO|RO|DX|TE|GOV` trailer.
2. If already pushed: add a follow-up commit with a `gov: add missing owner tags` note, OR accept the miss and improve the gate to block future occurrences.

## Prevention
`check_owner_tag.py` is wired in `claude-rules.yml` as an advisory gate; promote to blocking after one wave's adoption.
