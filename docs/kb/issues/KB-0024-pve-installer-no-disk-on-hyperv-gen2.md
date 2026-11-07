---
id: KB-0024
title: "Proxmox VE installer finds no ISO and no keyboard on a Hyper-V Gen 2 VM"
status: fixed
found_by: build
signal: "Installer: no installation medium found; rescue shell ignores the keyboard"
found: 2026-11-05
resolved: 2026-11-05
severity: high
hosts: [windows-host, pve01]
components: [proxmox-ve]
patterns: [nested-virtualization-quirks]
commits: [9b2bd0c]
related: [KB-0025]
---

# KB-0024: Proxmox VE installer finds no ISO and no keyboard on a Hyper-V Gen 2 VM

## Symptom

Installing Proxmox VE 9.2 in the Hyper-V VM pve01: the installer reported no installation medium, and its rescue shell took no keyboard input. The GRUB menu before it did take keys.

## How it was found

First install of pve01.

## Root cause

The installer's initrd loads modules in a single modalias pass that runs before `hv_vmbus` has enumerated the synthetic devices, so `hv_storvsc` (disks, the ISO) and `hyperv_keyboard` are never loaded on a Gen 2 VM.

## Fix

`host-setup/04-boot-pve-installer.ps1` types a GRUB command line through WMI (Msvm_Keyboard) that boots with `rdinit=/bin/sh` running `modprobe hyperv_keyboard; modprobe hv_storvsc; sleep 3; exec /init` first. Variants with `${IFS}` or unquoted words fail because GRUB itself parses `;` and `$`.

## Verification

The installer found the ISO and installed pve01.

## Prevention

Scripted, so a rebuild is repeatable. Side effect handled in KB-0025.
