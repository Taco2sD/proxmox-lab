---
id: KB-0051
title: "Removing ws03 failed CI, so the removal could never be released"
status: fixed
found_by: ci
signal: "tools/check: unit test failure"
found: 2026-11-07
resolved: 2026-11-07
severity: medium
hosts: [github]
components: [ci]
patterns: [ci-environment-mismatch]
commits: [f2e91db]
related: []
---

# KB-0051: Removing ws03 failed CI, so the removal could never be released

## Symptom

The admin page committed the removal of ws03 to main, CI failed, and `stable` never moved, so the reconciler never applied it.

## How it was found

CI failed on the commit the admin page made.

## Root cause

A unit test asserted on machines that happened to be in inventory/workstations/, so changing the fleet broke the test.

## Fix

Tests build their own inventory and don't depend on which fleet machines exist (f2e91db, `tests/test_lablib.py`).

## Verification

The removal passed CI and was applied.

## Prevention

Tests use fixtures, not live data.
