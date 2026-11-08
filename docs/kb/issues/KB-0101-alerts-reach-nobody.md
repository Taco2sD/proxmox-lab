---
id: KB-0101
title: Firing alerts reach nobody, and nothing watches the watcher
status: accepted
found_by: review
signal: "pre-mortem: no alerting section in prometheus.yml; Prometheus runs on mgmt01, which it also monitors"
found: 2026-11-07
severity: high
hosts: [mgmt01]
components: [prometheus, alert-rules, grafana, mgmt01]
patterns: [monitoring-blind-spot, unwatched-safety-net]
commits: []
related: [KB-0100, KB-0104]
---
## Symptom

The 20 alert rules fire into Prometheus's own alerts page and the Lab overview dashboard,
and nowhere else. An alert at 03:00 (the tunnel down, a disk filling, the reconciler stuck)
waits until someone happens to open Grafana. If mgmt01 itself stops (the LXC, its Docker,
or pve01 under it), the dashboards and alerts stop with it, and that silence looks the
same as "all clear".

## How it was found

Reading the monitoring configuration during the pre-mortem:

```
$ grep -c "alerting\|alertmanager" /etc/lab-monitoring/prometheus/prometheus.yml
0
```

docs/monitoring.md says so too ("There's no Alertmanager"). Prometheus, Grafana and every
exporter run on mgmt01 (roles/monitoring), and pve01 hosts mgmt01, so one host failure
blinds the whole stack. No check runs from outside the lab.

## Root cause

A scope choice made while building the monitoring, never revisited: collection and display
were built first, and delivery was left for later.

## Fix

**Decision (2026-11-08): accepted.** This is a demo lab with nobody on call: firing alerts on the Lab overview and Prometheus's alerts page are enough. Alertmanager stays the production answer.

Proposed in PLAN-0002, not applied:

1. **Delivery:** add Alertmanager (same compose project, 127.0.0.1) with one route to
   e-mail through the existing outbound mail service (Resend), grouped by `alertname, host`,
   `repeat_interval: 12h`, and inhibition so `TargetDown` for a host silences that host's
   other alerts.
2. **Dead man's switch:** an always-firing `Watchdog` rule whose notifications go to an
   external heartbeat checker (a healthchecks-style URL, or a tiny endpoint on the VPS). If
   the heartbeat stops, the external side alerts. That catches mgmt01, pve01 or the
   Windows host going down.
3. **Outside-in probe:** a check from the VPS (or GitHub Actions on a schedule) of
   https://lab.radicallydecent.com through the gate, which covers the tunnel, relay and
   portal path end to end.

## Verification

Not fixed yet. Done when stopping the Prometheus container on purpose produces an external
notification within 10 minutes, and a test alert arrives by e-mail.

## Prevention

Every alert rule must have a receiver, and the monitoring system must be monitored from
somewhere it doesn't run. See [monitoring-blind-spot](../patterns/monitoring-blind-spot.md).
