---
id: KB-0052
title: "Unit tests failed in CI: the lock directory is root-only"
status: fixed
found_by: ci
signal: "tools/check: unit tests failed on GitHub's runners"
found: 2026-11-07
resolved: 2026-11-07
severity: low
hosts: [github]
components: [ci, lab-cli]
patterns: [ci-environment-mismatch]
commits: [6fb43fc]
related: [KB-0053]
---

# KB-0052: Unit tests failed in CI: the lock directory is root-only

## Symptom

Tests that take locks passed on mgmt01 and failed on GitHub's runners.

## How it was found

First CI run.

## Root cause

lablib's locks lived in /run/lab, which exists on mgmt01 (tmpfiles.d) but isn't writable for CI's unprivileged user.

## Fix

The lock directory is overridable (`LAB_LOCKS`); tests use a temporary one (6fb43fc).

## Verification

CI green.

## Prevention

CI runs unprivileged on a fresh machine; nothing may assume mgmt01's directories.
