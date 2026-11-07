---
id: KB-0107
title: AD database health isn't checked; dbcheck already reports 5 dangling links from deleted workstations
status: open
found_by: review
signal: "pre-mortem: samba-tool dbcheck --cross-ncs on dc01 (read-only)"
found: 2026-11-07
severity: low
hosts: [dc01]
components: [samba-ad, alert-rules, backups]
patterns: [monitoring-blind-spot]
commits: []
related: [KB-0100]
---
## Symptom

dc01 is the lab's only domain controller, so its database is every login, DNS name and DHCP
registration. The probes show that its protocols answer (LDAPS, Kerberos, DNS), but nothing
checks the database itself. Samba's own consistency check already reports errors:

```
$ sudo samba-tool dbcheck --cross-ncs
WARNING: target DN is deleted for member in object CN=role-programmer,OU=Groups,OU=Lab,DC=ad,...
  Target GUID points at deleted DN 'CN=ws-tester\0ADEL:a53e4d1b-...,CN=Deleted Objects,...'
  Not removing
  (same for ws-murph, ws02 in role-programmer; ws-secure1, ws01 in role-artist)
Checked 3952 objects (5 errors)
```

## How it was found

Running `samba-tool dbcheck --cross-ncs` without `--fix` (read-only) during the pre-mortem.

## Root cause

When a workstation is deleted, its computer object becomes a tombstone, and its membership
in the `role-*` group stays behind as a link to that deleted object (here already marked
inactive, `RMD_FLAGS=1`). Samba cleans these after the tombstone lifetime. Until then,
dbcheck counts each one as an error, one per deleted workstation. They're harmless today,
but they mean a dbcheck run will never be clean, so a *real* inconsistency would hide among
them.

## Fix

Proposed in PLAN-0002, not applied:

1. **After** a verified backup of dc01 exists (KB-0100), run `samba-tool dbcheck
   --cross-ncs --fix --yes`, then re-run without `--fix` and expect 0 errors.
2. A weekly textfile metric on dc01, `lab_samba_dbcheck_errors` (plus the time of the last
   run), with an alert when it's above 0, and a runbook.
3. Optionally, have the delete path in `lab` remove the computer from its `role-*` group
   before deleting the object.

## Verification

Not fixed yet. Done when dbcheck reports 0 errors, and the metric shows on the Machine
dashboard for dc01.

## Prevention

Health checks the application itself provides (dbcheck, `pg_amcheck`, `zpool scrub`)
belong in monitoring next to the protocol probes. See
[monitoring-blind-spot](../patterns/monitoring-blind-spot.md).
