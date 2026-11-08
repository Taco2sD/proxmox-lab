---
id: KB-0100
title: dc01 and mgmt01 have never been backed up, and nothing would notice if backups stopped
status: mitigated
found_by: review
signal: "pre-mortem: pvesh get /nodes/pve01/storage/local/content --content backup (empty)"
found: 2026-11-07
resolved: 2026-11-08
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

Done on 2026-11-08:

1. **First backups exist.** The scheduled job ran at 03:30 (task log OK, guest agent
   fs-freeze/thaw around dc01's snapshot, so the image is filesystem-consistent):

   ```
   vzdump-qemu-105-2026_11_08-03_30_00.vma.zst  2.72 GB  (16 GiB disk, 65% zeros) 12 s
   vzdump-lxc-106-2026_11_08-03_30_12.tar.zst   3.32 GB                           29 s
   ```

2. **Both restored and checked, then destroyed** (throwaway IDs 990/991, `--unique 1`,
   network removed before anything could start them; dc01's copy never started, since a
   second DC with the same identity on the network would damage AD):
   - mgmt01 -> CT 991: `pct restore` took 9 s for 6.5 GiB. Mounted with `pct mount`:
     `/var/lib/lab/guests` (ws31..ws36), `observed.json` from 03:29:57, `reconcile.json`,
     the OpenTofu states in `/var/lib/lab/tofu`, `/etc/lab-monitoring` incl. `pve.env`,
     `/etc/proxmox-lab/tofu.env`, `/opt/proxmox-lab` on `stable`, Prometheus's data (135 MB).
   - dc01 -> VM 990: `qmrestore` took 11 s. Verified as far as the files: the OS disk's
     root filesystem (ext4, partition 2) mounted read-only on pve01 via `losetup -r -P`:
     hostname dc01, the AD partitions in `/var/lib/samba/private/sam.ldb.d` (domain
     partition modified 03:20 that night), `secrets.keytab`, `/etc/dnsmasq.d/lab-dhcp.conf`.
     Not verified: booting it and running `samba-tool dbcheck` (would need an isolated
     network; the read-only file check is as far as is safe here).
   - `qm destroy 990 --purge`, `pct destroy 991 --purge`: gone, thin pool back to 57.43%.

3. **Backup recency is measured and alerted.** roles/pve_backups now installs
   `lab-backup-metrics` (every 15 min, read-only `pvesh`): `lab_backup_expected`,
   `lab_backup_last_timestamp_seconds`, `lab_backup_last_size_bytes`,
   `lab_backup_archives` per guest. The alert BackupMissing
   ([runbook](../runbooks/BackupMissing.md)) fires when a covered guest's newest archive is
   over 26 h old or missing, or the collector itself goes stale.

Still open (why the status is *mitigated*, not *fixed*):

- **Off-host copy.** The archives sit on `local` on pve01: the same virtual disk, and the
  same physical drive (O: on the Windows host), as the VMs. Proposal for the owner: copy
  the newest archives nightly to the Windows host's other drive or, encrypted (they hold
  secrets), to the VPS. Not done: it's a decision about where secrets may live.
- **AD-level backup.** `samba-tool domain backup offline` next to the VM image, the
  supported way to restore AD on its own (PLAN-0001).

## Verification

```
$ cat /var/lib/prometheus/node-exporter/lab-backups.prom     # on pve01
lab_backup_expected{vmid="105",guest="dc01"} 1
lab_backup_expected{vmid="106",guest="mgmt01"} 1
lab_backup_last_timestamp_seconds{vmid="105",guest="dc01"} 1794105000
lab_backup_last_timestamp_seconds{vmid="106",guest="mgmt01"} 1794105012
lab_backup_archives{vmid="105",guest="dc01"} 1
```

BackupMissing is loaded and inactive while both are under 26 h old.

## Prevention

A safety net counts only once its result is measured: alert on "newest backup age", not on
"a job exists" ([unwatched-safety-net](../patterns/unwatched-safety-net.md)). A backup
counts only once a restore from it has been tried.
