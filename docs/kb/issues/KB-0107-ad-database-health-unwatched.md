---
id: KB-0107
title: AD database health isn't checked; dbcheck already reports 5 dangling links from deleted workstations
status: fixed
found_by: review
signal: "pre-mortem: samba-tool dbcheck --cross-ncs on dc01 (read-only)"
found: 2026-11-07
resolved: 2026-11-08
severity: low
hosts: [dc01]
components: [samba-ad, alert-rules, backups, node-exporter]
patterns: [monitoring-blind-spot]
commits: [0be641f, 00fe16c]
related: [KB-0100, KB-0029]
---
## Symptom

dc01 is the lab's only domain controller, so its database is every login, DNS name and DHCP
registration. The probes show that its protocols answer (LDAPS, Kerberos, DNS), but nothing
checked the database itself. Samba's own consistency check already reported errors:

```
$ sudo samba-tool dbcheck --cross-ncs
WARNING: target DN is deleted for member in object CN=role-programmer,OU=Groups,OU=Lab,DC=ad,...
  - <GUID=a53e4d1b-...>;...;<RMD_FLAGS=1>;...;CN=ws-tester,OU=Workstations,...
Target GUID points at deleted DN 'CN=ws-tester\0ADEL:a53e4d1b-...,CN=Deleted Objects,...'
Not removing
  (same for ws-murph, ws02 in role-programmer; ws-secure1, ws01 in role-artist)
Checked 3952 objects (5 errors)
```

## How it was found

Running `samba-tool dbcheck --cross-ncs` without `--fix` (read-only) during the pre-mortem.

## Root cause

Samba behaviour, not a bug in the lab's code. The lab deletes a workstation's computer
account with a plain `samba-tool computer delete`
(`ansible/roles/dc_identity/library/lab_dc_identity.py`). Samba then marks the group's
`member` link to it inactive (`RMD_FLAGS=1`) instead of removing it, and keeps the inactive
value for linked-value replication until the tombstone lifetime (180 days) runs out.

dbcheck (Samba 4.23.6, `samba/dbchecker.py`, `check_dn`) reports a link whose target is
deleted. When the target was deleted at or after the link's last change
(`deleted_usn >= RMD_LOCAL_USN`), it reports the link as a plausible leftover: a `WARNING`
with "Remove stale DN link?". That's every link here: one per deleted workstation, all
`WARNING`, no `ERROR`. Removing the computer from its `role-*` group before deleting it
wouldn't change anything: the link would still be inactive before the object was deleted,
which is exactly this case. The cost was a dbcheck that could never come back clean, so a
real inconsistency would have hidden among the leftovers.

## Fix

1. Backups first, since dc01 is the only DC: the nightly vzdump of VM 105 (2026-11-08 03:30) was
   restored to a scratch VM and checked read-only (KB-0100), and a Samba offline backup was
   taken: `samba-tool domain backup offline --targetdir=/var/backups/samba-20261108` on
   dc01 (root only, 700/600: it holds the password hashes).
2. `sudo samba-tool dbcheck --cross-ncs --fix --yes`: "Removed deleted DN on attribute
   member" five times.
3. The check is now monitoring: role `ansible/roles/samba_health` runs
   `/usr/local/libexec/lab-samba-dbcheck` daily at 04:30, after the nightly backup (and once
   10 minutes after boot). It runs dbcheck read-only (about 2.4 s for 3,952 objects) and writes
   textfile metrics for node_exporter:
   `lab_samba_dbcheck_problems{kind="error"|"stale_link"}`, `lab_samba_dbcheck_objects`,
   `lab_samba_dbcheck_success`, `lab_samba_dbcheck_last_run_timestamp_seconds`.
4. Alert `SambaDatabaseErrors` (group `directory` in
   `ansible/roles/monitoring/files/alerts.yml`) fires on real errors only, when the check
   failed, or when it hasn't run for two days. Stale links are counted but don't page anyone:
   every workstation delete creates one.
   Runbook: [SambaDatabaseErrors](../runbooks/SambaDatabaseErrors.md).

## Verification

```
$ sudo samba-tool dbcheck --cross-ncs          # after --fix
Checked 3952 objects (0 errors)
$ grep -v '^#' /var/lib/prometheus/node-exporter/samba_dbcheck.prom
lab_samba_dbcheck_problems{kind="error"} 0
lab_samba_dbcheck_problems{kind="stale_link"} 0
lab_samba_dbcheck_objects 3952
lab_samba_dbcheck_success 1
```

- AD still whole: `samba-tool user list` shows 19 users and `samba-tool computer list` 7;
  `role-artist` still holds the live ws31; samba-ad-dc active.
- On ws35, `id jrhodes` shows `ws-admins`, and `getent group ws-admins` resolves.
- Prometheus: `probe_success` is 1 for LDAPS, Kerberos and DNS (dc01). `promtool check rules` passes
  (24 rules), and the `SambaDatabaseErrors` expression returns nothing.

## Prevention

- The daily metric and alert make the database's health visible, next to the protocol
  probes.
- Every workstation deleted from now on adds one `stale_link`. They're harmless and
  expire after 180 days. To clear them sooner, run the runbook's fix after a backup.
  Leaving that step manual is deliberate: an automatic `--fix` on the only DC isn't worth
  the risk to save a few lines of output.
- Health checks the application itself provides (dbcheck, `pg_amcheck`, `zpool scrub`)
  belong in monitoring next to the protocol probes. See
  [monitoring-blind-spot](../patterns/monitoring-blind-spot.md).
