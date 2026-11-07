---
plan: PLAN-0002
title: Close the monitoring's blind spots and deliver its alerts
status: proposed
owner: unassigned
created: 2026-11-07
issues: [KB-0101, KB-0104, KB-0100, KB-0107, KB-0106]
patterns: [monitoring-blind-spot, unwatched-safety-net]
components: [prometheus, alert-rules, blackbox, node-exporter, dhcp, portal-relay, console-relay, backups, samba-ad]
---
## Goal

Every key component has an alert that fires when it stops, every alert reaches a person,
and the monitoring is watched from outside the host it runs on.

## Why

Today alerts go nowhere (KB-0101). Stopped services such as DHCP and the relays raise
nothing (KB-0104). Backup age, AD database health and thin-pool metadata aren't measured
(KB-0100, KB-0107, KB-0106).

## Steps

- [ ] `KeyServiceDown` rule (`node_systemd_unit_state{state="active",name=~"<key units>"} == 0`,
      for 2m), scoped per host, with a runbook. Test it by stopping dnsmasq on dc01 in a
      quiet moment.
- [ ] TCP probe of the console relay for one running guest from mgmt01, and of the portal
      relay. 10.99.0.2:8443 isn't reachable from mgmt01, so check it from pve01 with a
      textfile, or from the VPS.
- [ ] Backup-age textfile on pve01 (`lab_backup_newest_timestamp_seconds{vmid}`), plus a
      `BackupTooOld` alert (older than 26 h) and runbook.
- [ ] Weekly `samba-tool dbcheck` textfile on dc01 (`lab_samba_dbcheck_errors`), plus an alert.
- [ ] Thin-pool data and metadata percent textfile on pve01, plus an alert on metadata over
      70%.
- [ ] Alertmanager in the monitoring compose project: an e-mail receiver, grouping by
      `alertname, host`, and inhibition of a host's other alerts while its `TargetDown`
      fires.
- [ ] A `Watchdog` rule (always firing) routed to an external heartbeat, so silence from
      mgmt01, pve01 or the Windows host itself reaches someone.
- [ ] For every new rule: a runbook in docs/kb/runbooks/ and a `runbook_url` annotation
      (`tools/kb.py check` enforces both).

## Risks and rollback

- New rules can be noisy. Ship each with a `for:` and watch it for a day before adding it
  to delivery. Rollback is reverting the rule's commit (Prometheus reloads on deploy).
- Alertmanager's e-mail needs an SMTP credential on mgmt01. Treat it as a secret (the
  table in docs/operations.md) and never commit it.
- Stopping dnsmasq to test it briefly blocks new leases. Existing leases keep working.

## Done when

Stopping dnsmasq fires `KeyServiceDown` within 3 minutes and the e-mail arrives. Stopping
the Prometheus container produces an external heartbeat alert within 10 minutes. Backup
age, dbcheck errors and thin-pool metadata are on the dashboards with alerts.
