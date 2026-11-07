---
id: KB-0100
title: dc01 and mgmt01 have never been backed up, and nothing would notice if backups stopped
status: open
found_by: review
signal: "pre-mortem: pvesh get /nodes/pve01/storage/local/content --content backup (empty)"
found: 2026-11-07
severity: high
hosts: [pve01, dc01, mgmt01]
components: [backups, samba-ad, lab-cli, portal, proxmox-ve]
patterns: [unwatched-safety-net, monitoring-blind-spot]
commits: []
related: [KB-0101, KB-0103]
---
## Symptom

Nothing has failed yet. The only copies of the state that can't be rebuilt from git exist
once: the AD database on dc01 (users, groups, computer accounts, DNS), and mgmt01's
`/var/lib/lab` (guest records, OpenTofu states, guest passwords) plus its keys and
acme-dns accounts. docs/operations.md says both are restored from nightly backups, and
those backups don't exist yet.

## How it was found

The pre-mortem review checked backup recency instead of trusting the job definition:

```
$ pvesh get /cluster/backup        # the job exists
[{"id":"lab-servers","schedule":"03:30","vmid":"105,106","storage":"local","prune-backups":{"keep-last":"7"},
  "next-run":1794105000, ...}]
$ cat /var/lib/pve-manager/jobs/vzdump-lab-servers.json
{"time":1794032974,"state":"created",...}         # created 2026-11-07 07:29, after that night's 03:30
$ pvesh get /nodes/pve01/tasks --typefilter vzdump   # no vzdump task has ever run
$ ls /var/lib/vz/dump/                               # empty
```

The first run is due 2026-11-08 03:30.

## Root cause

Three separate gaps line up:

1. **Timing:** roles/pve_backups created the job on 2026-11-07 at 07:29, so no run has
   happened yet. That's not a bug, but nobody knew.
2. **No recency signal:** pve-exporter's `pve_not_backed_up_info` / `_total` only say
   whether a guest is *in* a backup job. dc01 and mgmt01 are in one, so they count as
   covered while having zero backups. No metric, alert or `lab doctor` check reads the age
   of the newest backup.
3. **Single copy on the same disk:** the job writes to `local` on pve01. That's the same
   virtual disk, and so the same physical drive (O: on the Windows host), as the VMs it
   protects. Losing pve01's disk or the Windows host loses the originals and the backups
   together. No restore has ever been tested.

## Fix

Proposed (PLAN-0001 and PLAN-0002), not applied:

1. After 03:30 on 2026-11-08, confirm both backups exist (`pvesh get
   /nodes/pve01/storage/local/content --content backup`), then test-restore mgmt01 to a
   spare CT ID with the network disconnected (`pct restore 9106 <archive> --storage
   local-lvm` with `--net0` removed), check `/var/lib/lab` is complete, and destroy it.
2. Add a backup-age metric (a textfile on pve01 from `pvesh get .../content --content
   backup`: newest `ctime` per VM ID) and an alert like `BackupTooOld` when the newest
   backup of 105 or 106 is older than 26 h. Add a runbook for it.
3. Copy each night's backups off pve01: at minimum to the Windows host's other drive or the
   VPS (the archives hold secrets, so encrypt them). For dc01, add `samba-tool domain backup
   offline`, the supported AD-level backup, next to the VM image.

## Verification

Not fixed yet. Done when the backup-age metric shows dc01 and mgmt01 under 26 h, a test
restore of mgmt01 has been done and written up, and an off-host copy exists.

## Prevention

A safety net counts only once its result is measured: alert on "newest backup age", not on
"a job exists". See [unwatched-safety-net](../patterns/unwatched-safety-net.md).
