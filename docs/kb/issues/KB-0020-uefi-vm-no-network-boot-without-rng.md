---
id: KB-0020
title: "UEFI VMs show no network boot entry at all"
status: fixed
found_by: build
signal: "OVMF boot menu without a PXE/HTTP boot option"
found: 2026-11-05
resolved: 2026-11-05
severity: high
hosts: [pve01]
components: [pxe-image-factory, proxmox-ve]
patterns: [upstream-default-changed]
commits: [9b2bd0c]
related: [KB-0021]
---

# KB-0020: UEFI VMs show no network boot entry at all

## Symptom

A UEFI VM set to boot from the network went straight to the EFI shell. The OVMF boot manager listed disks and the CD drive but no network entry, so PXE never started.

## How it was found

Hit on the first PXE install attempt on pve01 (pve-edk2-firmware 4.2026.08).

## Root cause

Since the 2024 PixieFail fixes, EDK2's network stack refuses to start without an entropy source. Proxmox's default CPU type (x86-64-v2-AES) doesn't expose RDRAND, and the VM had no virtio RNG, so OVMF silently left the network boot options out.

## Fix

Every VM that network-boots gets a virtio RNG fed from the host: `--rng0 source=/dev/urandom` by hand at first, now the `rng` block in `terraform/modules/workstation/main.tf` and the image builder's definition in `ansible/roles/runner/files/lab`.

## Verification

The OVMF boot menu showed the network entries and the VM fetched shim and GRUB over TFTP from mgmt01.

## Prevention

The RNG device is part of the VM definition in code, not a manual step. When a firmware update changes boot behaviour, test a PXE boot before relying on it. Fixed before the repository's history starts: the first commit (9b2bd0c) holds the state after the fix.
