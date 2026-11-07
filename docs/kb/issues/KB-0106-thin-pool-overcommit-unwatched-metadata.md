---
id: KB-0106
title: local-lvm is overcommitted with autoextend off, and its metadata use isn't monitored
status: open
found_by: review
signal: "pre-mortem: lvs -a on pve01; lvm.conf thin_pool_autoextend_* unset"
found: 2026-11-07
severity: low
hosts: [pve01]
components: [proxmox-ve, golden-image, workstations]
patterns: [disk-headroom, monitoring-blind-spot]
commits: []
related: [KB-0010]
---
## Symptom

Every VM disk lives on the thin pool `pve/data` (Proxmox's local-lvm). Its volumes have
been promised more space than the pool has, and nothing grows the pool automatically.
When a thin pool fills, every VM writing to it stops with I/O errors. If its *metadata*
fills, the pool can be damaged.

## How it was found

```
$ lvs -a -o lv_name,lv_size,data_percent,metadata_percent pve
  data   <154.11g  56.90  2.64
  vm-131-state-suspend-2026-11-07  <6.49g   ...   (one per hibernated machine)
$ vgs pve        ->  VFree 16.00g
$ grep -E "^\s*thin_pool_autoextend" /etc/lvm/lvm.conf   ->  (unset: threshold 100 = never)
WARNING: Sum of all thin volume sizes (<244.02 GiB) exceeds the size of thin pool pve/data
  (printed by lvresize when mgmt01's disk was grown, KB-0010)
```

What uses the pool besides workstation disks: two golden images per kind (A/B, 24 GB
each, kept while a new one is built), the image builder VM during a build, and one
`state-suspend` volume per hibernated machine (6.5 GB for a desktop, 2.5 GB for a devbox).
With 48-hour idle hibernation (KB-0014), these stay around longer.

## Root cause

Thin provisioning is Proxmox's default and the right choice here, but it comes with two
duties that weren't set up: watch real use including metadata, and keep space to grow.
The alert `StoragePoolAlmostFull` watches data use at 85% (pve-exporter). Metadata use
isn't exported at all.

## Fix

Proposed in PLAN-0003, not applied:

1. On pve01, `thin_pool_autoextend_threshold = 80` and `thin_pool_autoextend_percent = 10`
   in an lvm.conf drop-in (managed by a pve01 role). The VG's 16 GB free is the reserve.
2. Export data and metadata percent (a textfile from `lvs --reportformat json`) and alert
   on metadata over 70%.
3. Rough capacity line in docs/monitoring.md: today ~87 GB used. Worst case at
   `guest_memory_mb` is about 6 desktops × 24 GB + suspend states + 4 image volumes ≈ 200 GB
   on 154 GB if every disk filled. In practice disks are 20–45% full, which is why it's low.

## Verification

Not fixed yet. Done when `lvs` metadata percent is on the dashboard with an alert, and the
autoextend settings are in git.

## Prevention

Every overcommitted resource needs a usage alert *and* a headroom policy. See
[disk-headroom](../patterns/disk-headroom.md).
