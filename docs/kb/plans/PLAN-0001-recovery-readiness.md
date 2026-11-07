---
plan: PLAN-0001
title: Recovery readiness, before the interview on Tue 2026-11-10
status: proposed
owner: unassigned
created: 2026-11-07
issues: [KB-0100, KB-0103, KB-0107]
patterns: [unwatched-safety-net, unmanaged-lower-layer]
components: [backups, samba-ad, mgmt01, dc01, windows-host, proxmox-ve]
---
## Goal

By Monday evening: proven backups of dc01 and mgmt01, one tested restore, and no unplanned
reboot of the Windows host possible during the interview.

## Why

The two servers whose state git can't rebuild have never been backed up (KB-0100). The
Windows host under the whole lab has a reboot pending (KB-0103). Either could end the demo,
and the first would make it unrecoverable.

## Steps

- [ ] Sun 2026-11-08 after 03:30: `pvesh get /nodes/pve01/storage/local/content --content backup`
      shows one archive each for 105 and 106. If not, read the vzdump task log
      (`pvesh get /nodes/pve01/tasks --typefilter vzdump`) and run
      `vzdump 105 106 --storage local --mode snapshot --compress zstd` by hand.
- [ ] Test-restore mgmt01 to CT 9106 without network (`pct restore 9106 <archive> --storage
      local-lvm`, then `pct set 9106 --delete net0` before starting it), check that
      `/var/lib/lab` and `/etc/lab-portal` are there, then `pct destroy 9106`. Record the
      result in KB-0100.
- [ ] dc01: run `samba-tool domain backup offline --targetdir=/var/backups/samba` once, and
      copy the archive off dc01.
- [ ] Copy the newest archives of 105 and 106 off pve01 (to the Windows host's data drive) as
      a stop-gap off-host copy.
- [ ] With a dc01 backup verified: `samba-tool dbcheck --cross-ncs --fix --yes` on dc01, then
      a read-only run reports 0 errors (KB-0107).
- [ ] The user's call: reboot the Windows PC deliberately (e.g. Sunday afternoon), watch the
      lab come back on the Lab overview (TargetDown, ClockSkew and TunnelDown clear), then
      pause Windows Update until 2026-11-12 (KB-0103).

## Risks and rollback

- The test restore uses a new CT ID with no network, so it can't clash with the live mgmt01
  (same MAC and IP) and is deleted afterwards. It must never start with `net0`.
- `dbcheck --fix` changes the AD database. Run it only after the dc01 backup is verified.
  Rollback is restoring VM 105 from that backup.
- The Windows reboot restarts everything. Do it when nothing is being built (the admin
  page's Activity list is empty). No rollback is needed, but allow 15 minutes for the lab to
  settle.

## Done when

Two dated archives exist on pve01 and a copy exists off it, KB-0100 records a successful
test restore, dbcheck reports 0 errors, and the PC has rebooted on purpose with the lab back
green and Windows Update showing "paused".
