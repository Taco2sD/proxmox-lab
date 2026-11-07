---
id: KB-0043
title: "Operations whose lab process died stayed 'In progress' forever"
status: fixed
found_by: build
signal: "Admin page Activity: In progress for hours"
found: 2026-11-07
resolved: 2026-11-07
severity: medium
hosts: [mgmt01]
components: [portal-worker]
patterns: [lost-work-on-restart]
commits: [613c753]
related: [KB-0042, KB-0044]
---

# KB-0043: Operations whose lab process died stayed "In progress" forever

## Symptom

An operation stayed "In progress" on the admin page long after anything was running.

## How it was found

Seen on the admin page's Activity list.

## Root cause

The record is updated by the `lab` process itself; when that process died (terminal closed, unit killed), nothing ever closed the record.

## Fix

The worker closes operations whose `lab` process no longer exists (613c753, `ansible/roles/portal/files/worker.py`).

## Verification

Operations left In progress by a dead `lab` process are now closed as failed by the worker's next pass (it checks the unit, or the pid's command line, in /proc).

## Prevention

State that only the doer can update needs a reaper that checks the doer is alive.
