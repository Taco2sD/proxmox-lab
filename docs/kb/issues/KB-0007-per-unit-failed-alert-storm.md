---
id: KB-0007
title: One alert per failed systemd unit turned one leaking template unit into ~1,700 alerts
status: fixed
found_by: monitoring
signal: 1,670 firing alerts on the Lab overview
found: 2026-11-07
resolved: 2026-11-07
severity: medium
hosts: [mgmt01, pve01]
components: [alert-rules, node-exporter, grafana]
patterns: [alert-cardinality-storm]
commits: [3d34679]
related: [KB-0001, KB-0006, KB-0008]
---
## Symptom

The Lab overview's "Firing alerts" stat read 1,670, and the alert table was a wall of
`SystemdUnitFailed` rows, all for pve01, each a different `lab-console@<n>-...service`.
Anything else that fired would have been lost in it.

## How it was found

The first screenshot of the dashboard after the alert table was fixed to show every
alert (KB-0009). Prometheus's rules API showed the same: one alert instance per failed
unit.

## Root cause

The rule was written per unit (`node_systemd_unit_state{state="failed"} == 1`), so its
alert count followed the number of failed units. On pve01, the console relay's
socket-activated template unit (`Accept=yes`) leaves a failed instance per refused
connection, and a browser retrying every few seconds produced thousands (KB-0001). The
alert's cardinality was set by a label nobody acts on individually.

## Fix

`SystemdUnitsFailed`: `count by (host) (node_systemd_unit_state{state="failed"} == 1)`,
one alert per machine whose value is the number of failed units. The Machine dashboard's
"Failed systemd units" table lists them, live (`systemctl --failed` on the machine is the
same list). The description points at `systemctl reset-failed` for units that won't run
again.

## Verification

After the reload: `SystemdUnitsFailed` had five instances (mgmt01 1, pve01 1.72e+03,
dc01 1, ws35 3, ws36 3) instead of ~1,700. (The reload itself only took effect after
KB-0008 was fixed; until then Prometheus still evaluated the old rule file.)

## Prevention

Rule of thumb in docs/monitoring.md: one alert per thing someone fixes. Before adding a
rule, check which labels its result keeps: a `by (...)` that reduces to the unit of
action (a machine, a service, a certificate) bounds the count. The pattern page lists the
signals.
