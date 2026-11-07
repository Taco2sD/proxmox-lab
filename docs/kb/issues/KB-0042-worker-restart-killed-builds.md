---
id: KB-0042
title: "A worker restart could kill a build halfway"
status: fixed
found_by: build
signal: "Build stuck after a deployment restarted lab-portal-worker"
found: 2026-11-07
resolved: 2026-11-07
severity: high
hosts: [mgmt01]
components: [portal-worker, lab-cli]
patterns: [lost-work-on-restart]
commits: [b589336]
related: [KB-0043, KB-0044]
---

# KB-0042: A worker restart could kill a build halfway

## Symptom

Deploying the portal while a machine was building could leave the build half-done.

## How it was found

Design review during the 2026-11-07 restructure: deployments restart the worker, and builds were its children.

## Root cause

Builds ran as child processes of the portal's worker; restarting the worker (every deployment) killed them.

## Fix

Every operation runs in its own transient systemd unit, `lab-op-<id>`, independent of the worker (b589336; `ansible/roles/runner/files/lab`).

## Verification

Restarting the worker during a build no longer affects it; `journalctl -u lab-op-<id>` shows its log.

## Prevention

Long work never lives inside a process that deployments restart.
