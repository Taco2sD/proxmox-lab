---
id: KB-0010
title: mgmt01's root disk was too small for the monitoring stack
status: fixed
found_by: build
signal: df -h / on mgmt01 (3.5 GB free) against the monitoring images (about 2.6 GB) plus Prometheus's data
found: 2026-11-07
resolved: 2026-11-07
severity: medium
hosts: [mgmt01, pve01]
components: [docker, prometheus, grafana, proxmox-ve]
patterns: [disk-headroom]
commits: []
related: []
---
## Symptom

mgmt01 (LXC 106) had an 8 GB root disk, 54% used, 3.5 GB free. The monitoring images alone are
about 2.6 GB (Grafana 1.95 GB), and Prometheus needs room for up to 2 GB of data.

## How it was found

While planning the monitoring build: a headroom check before pulling the images, not a failure.

## Root cause

mgmt01 was sized for the runner, the portal and Guacamole. Each Docker service added since has
taken a large share of a small disk.

## Fix

Grown online on pve01: `pct resize 106 rootfs +6G` (8 to 14 GB, resize2fs ran on-line), leaving
9.1 GB free. Prometheus is capped at `--storage.tsdb.retention.size=2GB`. The container's size is
set by hand on pve01, not by Ansible or OpenTofu (mgmt01 predates both), so this change lives only
in Proxmox's config.

## Verification

`pct config 106` shows `size=14G`; `df -h /` on mgmt01 showed 14G, 4.0G used, 9.1G free before
the pulls; all four images pulled.

## Prevention

Check headroom before adding data or images; DiskFillingUp and DiskAlmostFull watch mgmt01's
root. pve01 warned the thin pool is overcommitted (244 GB of volumes on a smaller pool):
StoragePoolAlmostFull watches its real use.
