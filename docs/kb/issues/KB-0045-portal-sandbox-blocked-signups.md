---
id: KB-0045
title: "The portal couldn't save sign-ups: its systemd sandbox made the paths read-only"
status: fixed
found_by: build
signal: "Welcome page sign-up failed"
found: 2026-11-07
resolved: 2026-11-07
severity: medium
hosts: [mgmt01]
components: [portal]
patterns: []
commits: [fec395c]
related: [KB-0044]
---

# KB-0045: The portal couldn't save sign-ups: its systemd sandbox made the paths read-only

## Symptom

Staff sign-ups on the welcome page failed to save.

## How it was found

First test of the welcome page.

## Root cause

`lab-portal.service` runs sandboxed with an explicit list of writable paths; the new invites/ directory and /run/lab/signups weren't on it, so the sandbox refused the writes.

## Fix

Added both to `ReadWritePaths` (fec395c, `ansible/roles/portal/files/lab-portal.service`).

## Verification

Sign-ups saved and the worker picked them up.

## Prevention

When a sandboxed service gets a new state path, the unit's ReadWritePaths changes in the same commit.
