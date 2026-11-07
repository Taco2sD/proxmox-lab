---
plan: PLAN-0003
title: Capacity headroom and housekeeping on pve01 and mgmt01
status: proposed
owner: unassigned
created: 2026-11-07
issues: [KB-0106, KB-0010]
patterns: [disk-headroom]
components: [proxmox-ve, mgmt01, docker, prometheus, golden-image]
---
## Goal

No disk on the lab's critical path can fill up silently, and the things that only grow
(thin-pool volumes, Docker images, logs) have a policy.

## Why

The thin pool is overcommitted with autoextend off (KB-0106). mgmt01 has already run out of
room once (KB-0010). Docker keeps every old image after an upgrade: 4.1 GB of images
today, on a 14 GB root where Prometheus may use 2 GB.

## Steps

- [ ] An lvm.conf drop-in on pve01, managed by a pve01 role: `thin_pool_autoextend_threshold = 80`,
      `thin_pool_autoextend_percent = 10`.
- [ ] Thin-pool data and metadata metric with an alert (owned by PLAN-0002; listed here
      only as a dependency).
- [ ] mgmt01: after an image upgrade in roles/monitoring or roles/guacamole, run
      `docker image prune -f` (a handler on the compose file change), so old tags don't
      accumulate.
- [ ] A capacity note in docs/monitoring.md: today's use, the worst case at
      `guest_memory_mb`, and when to grow (pool over 70%, mgmt01 root over 75%).
- [ ] Golden images: confirm `lab image build` deletes the previous A/B template after
      switching (two per kind is the design), so templates don't pile up.

## Risks and rollback

- Autoextend draws on the VG's 16 GB free. That's the intended reserve, and removing the
  drop-in reverts it.
- `docker image prune -f` removes only dangling images, never one a container uses.

## Done when

Autoextend is in git, the thin-pool metadata alert exists, an image upgrade leaves no old
images behind, and docs/monitoring.md states the capacity limits.
