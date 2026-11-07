---
id: KB-0028
title: "ansible-pull couldn't clone from the first in-lab git server"
status: fixed
found_by: build
signal: "ansible-pull: clone failed"
found: 2026-11-05
resolved: 2026-11-06
severity: medium
hosts: [workstations, mgmt01]
components: [ansible-pull]
patterns: []
commits: [9b2bd0c]
related: []
---

# KB-0028: ansible-pull couldn't clone from the first in-lab git server

## Symptom

Workstations' first `ansible-pull` failed to clone the configuration repository.

## How it was found

First self-managing workstation (ws01).

## Root cause

The repository was served by plain nginx (git's "dumb HTTP"), which can't do the shallow clone ansible-pull asks for by default.

## Fix

`--full` at first. Since 2026-11-06 workstations pull the public GitHub repository, which supports shallow clones (`ansible/roles/base/templates/ansible-pull.service.j2`).

## Verification

ws01 cloned and applied its configuration.

## Prevention

One source of truth (GitHub) instead of a second git server to keep running.
