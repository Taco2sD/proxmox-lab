---
id: KB-0032
title: "A reimaged VM reinstalled itself eight times"
status: fixed
found_by: build
signal: "VM PXE-booted into the installer again after every install"
found: 2026-11-06
resolved: 2026-11-06
severity: medium
hosts: [pve01, workstations]
components: [proxmox-ve, lab-cli]
patterns: []
commits: [9b2bd0c, 1bb2a60]
related: []
---

# KB-0032: A reimaged VM reinstalled itself eight times

## Symptom

The first reimage of ws03 installed, rebooted, and installed again, eight times over.

## How it was found

Watching the console during the first hands-off reimage.

## Root cause

The reimage script used `qm disk unlink scsi0` to replace the disk. Unlinking also removes the disk from the VM's boot order, so after each install the VM fell through to network boot and reinstalled.

## Fix

The script set `--boot order=scsi0;net0` explicitly; the VM definition now lives in OpenTofu (`terraform/modules/workstation`), which declares the boot order, and the old script was retired (1bb2a60).

## Verification

The next reimage booted from disk after one install.

## Prevention

Declare boot order in the VM definition instead of relying on it surviving disk operations.
