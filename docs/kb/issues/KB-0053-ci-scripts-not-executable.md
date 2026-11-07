---
id: KB-0053
title: "CI couldn't run tools/check: scripts weren't executable in git"
status: fixed
found_by: ci
signal: "GitHub Actions: tools/check could not be executed"
found: 2026-11-07
resolved: 2026-11-07
severity: low
hosts: [github]
components: [ci]
patterns: [ci-environment-mismatch]
commits: [2b924c7]
related: [KB-0052]
---

# KB-0053: CI couldn't run tools/check: scripts weren't executable in git

## Symptom

The checks workflow failed before running anything: tools/check wasn't executable.

## How it was found

First CI run.

## Root cause

The files were committed from Windows without the executable bit. The OpenTofu setup action also ran on the deprecated Node 20 runtime.

## Fix

`git update-index --chmod=+x` for the scripts, and OpenTofu installed by verified download instead of the action (2b924c7, `.github/workflows/checks.yml`).

## Verification

CI green.

## Prevention

Mode bits live in git; set them there, not on disk.
