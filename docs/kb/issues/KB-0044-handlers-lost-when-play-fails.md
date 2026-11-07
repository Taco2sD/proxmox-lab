---
id: KB-0044
title: "A failed run dropped notified handlers, so the old code kept running"
status: fixed
found_by: build
signal: "Portal kept running old code after a deploy"
found: 2026-11-07
resolved: 2026-11-07
severity: medium
hosts: [mgmt01]
components: [reconciler, portal]
patterns: [lost-work-on-restart]
commits: [fec395c]
related: [KB-0045]
---

# KB-0044: A failed run dropped notified handlers, so the old code kept running

## Symptom

After a deployment in which a later task failed, the portal still ran the previous code, and fixing the failure didn't restart it.

## How it was found

A portal change didn't take effect after a deployment that failed partway (the example in `ansible.cfg`: "Restart portal" after new files were copied).

## Root cause

Ansible drops notified handlers when a play fails. The next run finds the files already in place, notifies nothing, and the restart never happens.

## Fix

`force_handlers = True` in `ansible.cfg` (fec395c).

## Verification

Not tested separately: this is Ansible's documented `force_handlers` behaviour. Later failed deploys (KB-0049, KB-0050) left no stale services behind.

## Prevention

Repo-wide setting, explained in `ansible.cfg`.
