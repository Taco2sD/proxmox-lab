---
id: KB-0063
title: CI failed when GitHub's release download answered 504
status: fixed
found_by: ci
signal: "GitHub Actions: curl: (22) The requested URL returned error: 504 (OpenTofu step)"
found: 2026-11-08
resolved: 2026-11-08
severity: low
hosts: [github]
components: [ci]
patterns: [upstream-outage]
commits: []
related: [KB-0053]
---

# KB-0063: CI failed when GitHub's release download answered 504

## Symptom

Two consecutive runs of the checks (commits 00fe16c and 55c8aca) failed in the
"OpenTofu" step, before any of the lab's own checks ran:
`curl: (22) The requested URL returned error: 504`, then
`sha256sum: 'standard input': no properly formatted checksum lines found`. `stable`
stayed on the previous release, so the lab kept running the older commit.

## How it was found

The CI run for the change failed; its log showed the download error. The same URL
answered 504 from the Windows host as well
(`curl -L https://github.com/opentofu/opentofu/releases/download/v1.13.9/tofu_1.13.9_SHA256SUMS`),
so the fault was GitHub's, not the change's.

## Root cause

The workflow downloaded OpenTofu with a single `curl -f` per file and no retries
(`.github/workflows/checks.yml`). Any transient error on GitHub's release downloads
failed the whole run.

## Fix

Both downloads go through `curl --retry 6 --retry-delay 10 --retry-all-errors` (about
two minutes of retries). The checksum check is unchanged, so a retried download is
still verified against the release's own SHA256SUMS.

## Verification

The run for the fix itself passed once GitHub's downloads recovered (see the commit's
CI run). A longer outage still fails the run, which is correct: the checks can't run
without the tool.

## Prevention

Pattern [upstream-outage](../patterns/upstream-outage.md): every fetch from an outside
service retries transient errors and keeps its checksum or certificate verification.
