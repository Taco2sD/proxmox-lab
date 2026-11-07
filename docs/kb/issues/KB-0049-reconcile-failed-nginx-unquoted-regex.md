---
id: KB-0049
title: "Reconciler deploy failed: nginx rejected an unquoted regex with braces"
status: fixed
found_by: build
signal: "Reconcile operation failed (ansible/site.yml)"
found: 2026-11-07
resolved: 2026-11-07
severity: medium
hosts: [mgmt01]
components: [nginx, reconciler, ci]
patterns: [ci-blind-spot]
commits: [e653da0]
related: [KB-0006, KB-0050]
---

# KB-0049: Reconciler deploy failed: nginx rejected an unquoted regex with braces

## Symptom

Operation 20261107-121546-reconcile-8131 failed: `nginx -t` reported `unknown directive "1,19}$"` in /etc/nginx/snippets/lab-keys.conf.

## How it was found

The reconciler's run after CI passed failed, and the admin page's Activity showed it.

## Root cause

A `location ~` regex with a `{1,19}` quantifier was unquoted; nginx reads `{` as the start of a block. CI doesn't run `nginx -t`, so the commit passed its checks.

## Fix

Quote the regex (e653da0, `ansible/roles/lab_web/files/lab-keys.conf`). The handler's `nginx -t` stopped the reload, so the running config was never broken.

## Verification

The next reconcile deployed cleanly.

## Prevention

Validate-before-reload kept the outage at zero. One of the failures the first OperationsFailing alert counted (KB-0006).
