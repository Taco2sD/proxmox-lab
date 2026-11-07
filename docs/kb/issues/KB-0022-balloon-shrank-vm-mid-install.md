---
id: KB-0022
title: "Memory ballooning deadlocked the installer: 'System is deadlocked on memory'"
status: fixed
found_by: build
signal: "Kernel panic on the VM console during install"
found: 2026-11-06
resolved: 2026-11-06
severity: high
hosts: [pve01, workstations]
components: [opentofu, proxmox-ve, pxe-image-factory]
patterns: [ram-backed-installer-limits]
commits: [9d568a0, f3a1e98]
related: [KB-0021]
---

# KB-0022: Memory ballooning deadlocked the installer: "System is deadlocked on memory"

## Symptom

A workstation being installed over PXE panicked with "System is deadlocked on memory".

## How it was found

Hit right after giving workstations a ballooning range of 2-5 GB (9d568a0) so the netboot installer would fit without manual resizing.

## Root cause

With a floating range, Proxmox's balloon driver took memory back from the VM while the installer was running. The installer keeps the whole ISO in RAM (KB-0021) and can't give it back, so the guest ran out of memory and the kernel gave up.

## Fix

Fixed memory, no ballooning range (f3a1e98). The balloon device stays, with free-page reporting on, so idle guests still return unused pages.

## Verification

The next install ran to completion at a fixed 5 GB.

## Prevention

Installs no longer happen on workstations at all (golden image clones). Anything RAM-backed must not have its memory managed from outside.
