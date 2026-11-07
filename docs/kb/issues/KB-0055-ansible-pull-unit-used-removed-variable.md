---
id: KB-0055
title: "Workstations' ansible-pull unit referenced a variable removed in the settings rewrite"
status: fixed
found_by: build
signal: "ansible-pull.service failed"
found: 2026-11-07
resolved: 2026-11-07
severity: high
hosts: [workstations]
components: [ansible-pull]
patterns: [ci-blind-spot]
commits: [b399a7a]
related: []
---

# KB-0055: Workstations' ansible-pull unit referenced a variable removed in the settings rewrite

## Symptom

After the 2026-11-07 settings rewrite, workstations' scheduled configuration runs failed to start the playbook.

## How it was found

Workstations stopped reporting finished configuration runs after the restructure.

## Root cause

`ansible-pull.service.j2` named the playbook through a variable that the rewrite removed; templates are only rendered on the workstation, so nothing in CI noticed.

## Fix

The unit names `ansible/local.yml` directly (b399a7a, `ansible/roles/base/templates/ansible-pull.service.j2`).

## Verification

Scheduled runs succeeded again.

## Prevention

WorkstationNotCheckingIn now alerts when a running machine hasn't finished a run for two hours.
