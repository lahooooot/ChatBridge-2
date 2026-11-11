## Summary

Describe what this change does and why.

## Changes

- 

## Checklist

- [ ] `python scripts/ver_check.py` passes (version markers synchronized)
- [ ] `python -m pytest -q` passes
- [ ] UI changes verified in the running app
- [ ] `CHANGELOG.md` updated under `[Unreleased]` if user-facing

## Release

When merging a release, bump the version in every marker file, update
`CHANGELOG.md`, then push a `vX.Y.Z` tag to trigger the release workflow.
