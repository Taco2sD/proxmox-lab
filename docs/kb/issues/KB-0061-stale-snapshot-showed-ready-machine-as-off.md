---
id: KB-0061
title: "My lab showed a machine that just became ready or woke up as still off"
status: fixed
found_by: build
signal: "Status lag on My lab"
found: 2026-11-07
resolved: 2026-11-07
severity: low
hosts: [mgmt01]
components: [portal, portal-worker]
patterns: []
commits: [24d9f8c]
related: []
---

# KB-0061: My lab showed a machine that just became ready or woke up as still off

## Symptom

A machine that had just finished building, or had just been woken, showed as stopped for up to a minute.

## How it was found

Using My lab.

## Root cause

The page combined the latest events with the worker's Proxmox snapshot (observed.json, once a minute), and the older snapshot overrode the newer event.

## Fix

The snapshot is refreshed when a machine becomes ready or wakes, and newer events win over an older snapshot (24d9f8c).

## Verification

Machines show as running at once.

## Prevention

Merge state by timestamp, not by source.
