---
id: KB-0062
title: "A machine started outside My lab was hibernated as idle within a minute"
status: fixed
found_by: build
signal: "Machine hibernated right after a manual start"
found: 2026-11-07
resolved: 2026-11-07
severity: medium
hosts: [mgmt01, workstations]
components: [portal-worker]
patterns: []
commits: [613c753]
related: [KB-0014, KB-0043]
---

# KB-0062: A machine started outside My lab was hibernated as idle within a minute

## Symptom

Starting a staff machine from the Proxmox UI was followed by the worker hibernating it as idle.

## How it was found

Starting ws31 from the Proxmox UI.

## Root cause

The idle rule measured from the last activity report, last resume through My lab or ready time. A start outside My lab updated none of them, so the machine looked idle for hours.

## Fix

The VM's own uptime counts as activity: started = observation time minus uptime (613c753, `ansible/roles/portal/files/worker.py`).

## Verification

A Proxmox-UI start stayed running.

## Prevention

Silence from a push beacon is ambiguous; the idle limit is now 48 hours (KB-0014).
