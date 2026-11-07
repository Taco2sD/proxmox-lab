---
id: KB-0021
title: "Ubuntu netboot installer runs out of space even with 7 GB of RAM"
status: fixed
found_by: build
signal: "'No space left on device' in the installer"
found: 2026-11-05
resolved: 2026-11-05
severity: high
hosts: [pve01]
components: [pxe-image-factory]
patterns: [ram-backed-installer-limits]
commits: [9b2bd0c]
related: [KB-0022, KB-0023]
---

# KB-0021: Ubuntu netboot installer runs out of space even with 7 GB of RAM

## Symptom

The PXE-booted Ubuntu installer failed while downloading the ISO with "No space left on device", even after the VM's memory went to 7 GB.

## How it was found

Hit on the first netboot install of a workstation.

## Root cause

With `url=` netboot, casper downloads the whole 2.73 GiB ISO into the initramfs root filesystem, a tmpfs. On kernel 7.0 that tmpfs is capped at 40% of RAM (measured), so more memory raised the cap too slowly to fit the ISO plus the unpacked system.

## Fix

`initramfs_options=size=90%` on the installer's kernel command line (before `---`), supported from kernel 7.0. It lives in `ansible/roles/pxe/templates/grub.cfg.j2`. Installs then fit in 5 GB; the VM can shrink afterwards.

## Verification

The installer completed with the ISO held in RAM.

## Prevention

The image factory is the only thing that runs the installer now; workstations are clones of the golden image (KB-0023 has the related memory limits). Fixed before the repository's history starts: the first commit (9b2bd0c) holds the state after the fix.
