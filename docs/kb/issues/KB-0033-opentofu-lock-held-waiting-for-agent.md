---
id: KB-0033
title: "A reimage held the OpenTofu state lock for 15 minutes"
status: fixed
found_by: build
signal: "OpenTofu: state lock held; plan blocked"
found: 2026-11-06
resolved: 2026-11-06
severity: medium
hosts: [mgmt01, pve01]
components: [opentofu]
patterns: [default-doesnt-fit]
commits: [115841b, abfc66e]
related: []
---

# KB-0033: A reimage held the OpenTofu state lock for 15 minutes

## Symptom

During a reimage every other `lab plan`/`lab apply` waited on the state lock, for up to 15 minutes.

## How it was found

A second `lab` command blocked while a reimage was running.

## Root cause

The bpg/proxmox provider waits up to 15 minutes for the QEMU guest agent to report IP addresses. An installing or crashed VM has no agent, so the provider sat in that wait holding the lock. Destroying a crashed VM also waited for a clean shutdown that never came.

## Fix

`agent.timeout = "30s"` (115841b) and `stop_on_destroy = true` (abfc66e) in `terraform/modules/workstation/main.tf`.

## Verification

Reimages released the lock within seconds of the VM being created.

## Prevention

Review provider defaults for waits on things that may never answer.
