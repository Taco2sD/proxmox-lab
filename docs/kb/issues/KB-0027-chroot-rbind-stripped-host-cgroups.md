---
id: KB-0027
title: "Leaving a chroot on pve01 unmounted the host's own /sys/fs/cgroup and hung its reboot"
status: fixed
found_by: investigation
signal: "pve01 reboot hung"
found: 2026-11-05
resolved: 2026-11-05
severity: high
hosts: [pve01]
components: [proxmox-ve]
patterns: []
commits: []
related: []
---

# KB-0027: Leaving a chroot on pve01 unmounted the host's own /sys/fs/cgroup and hung its reboot

## Symptom

After a chroot session on pve01, pve01's next reboot hung.

## How it was found

pve01 didn't come back from a reboot after the chroot session.

## Root cause

The chroot had bind-mounted `/sys` with plain `mount --rbind`. Without making the mount a slave, the later `umount -l` propagated back to the host and took `/sys/fs/cgroup` with it, which systemd needs to stop services.

## Fix

Procedure: `mount --rbind /sys <root>/sys && mount --make-rslave <root>/sys` (same for `/dev`), so unmounts inside the chroot don't propagate to the host.

## Verification

The next chroot session on pve01 ended without affecting the host.

## Prevention

Prefer the guest agent or a rescue VM over chrooting on the hypervisor. When a chroot is unavoidable, always `--make-rslave`.
