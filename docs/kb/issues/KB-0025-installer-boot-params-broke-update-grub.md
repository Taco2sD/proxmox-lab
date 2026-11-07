---
id: KB-0025
title: "Proxmox's installer copied its boot parameters into GRUB's config and broke update-grub"
status: fixed
found_by: build
signal: "pve01 booted to a bare grub> prompt"
found: 2026-11-05
resolved: 2026-11-05
severity: high
hosts: [pve01]
components: [proxmox-ve]
patterns: [nested-virtualization-quirks]
commits: [9b2bd0c]
related: [KB-0024]
---

# KB-0025: Proxmox's installer copied its boot parameters into GRUB's config and broke update-grub

## Symptom

After the first `update-grub` on pve01, the next boot stopped at a bare `grub>` prompt.

## How it was found

Rebooting pve01 after post-install updates.

## Root cause

The installer saved the workaround parameters from KB-0024 into `/etc/default/grub.d/installer.cfg`. Their quoting broke the generated config, so `update-grub` wrote no usable grub.cfg.

## Fix

Removed the file and regenerated the config; `host-setup/03-pve-postinstall.sh` now deletes it on every new install.

## Verification

pve01 booted normally after `update-grub`.

## Prevention

The post-install script owns the cleanup. A workaround passed on a kernel command line can be persisted by an installer, so check what it leaves behind.
