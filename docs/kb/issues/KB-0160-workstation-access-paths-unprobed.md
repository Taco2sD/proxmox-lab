---
id: KB-0160
title: Nothing checked that people can actually reach their workstations (SSH, Desktop console)
status: fixed
found_by: review
signal: KB-0001 follow-up (relay refusals no longer show as failed units)
found: 2026-11-07
resolved: 2026-11-07
severity: medium
hosts: [mgmt01, pve01, workstations]
components: [blackbox, lab-metrics, console-relay, alert-rules, workstations]
patterns: [monitoring-blind-spot]
commits: [8d36926, 00fe16c]
related: [KB-0001]
---
## Symptom

No symptom yet: this was anticipated. The two ways people reach their machines, SSH
(including the portal's browser terminal) and the Desktop button (Guacamole through pve01's
console relay), weren't probed at all. A workstation could be "up" to Prometheus
(node_exporter answering on :9100) while its sshd was dead or the relay refused it, and
nothing would say so until someone complained.

## How it was found

Fixing KB-0001 removed the one accidental signal the relay had: its refusals used to leave
failed `lab-console@` units behind, and SystemdUnitsFailed fired on them. After the fix, a
refusal is a clean exit and a broken relay would be invisible. A review of what the
monitoring covers per user path (the portal, Guacamole and the VPS were probed; the
per-machine paths weren't) found the gap.

## Root cause

The service probes in `ansible/roles/monitoring/templates/prometheus.yml.j2` are a static
list, written for things that exist once (the portal, LDAPS, DNS). Per-machine paths come
and go with the machines, so they need a target list that follows them, like the
workstation scrape targets do.

## Fix

- `lab-metrics` writes a second file_sd list,
  `/etc/lab-monitoring/prometheus/targets/access.json`: for every running, ready
  workstation an SSH probe of `<ip>:22`, and for desktop machines a probe of the console
  relay at `pve01:<console_port_base + vmid>`. Labels: host, owner, role, kind, probe
  ("SSH" or "Desktop console").
- blackbox modules `ssh_banner` (expects `SSH-2.0-`, then sends its own identification so
  sshd logs one tidy `Connection closed ... [preauth]` line instead of a
  `kex_exchange_identification` error) and `rfb_banner` (expects `RFB 003`). Both stop
  after the banner: no login, no VNC handshake, so an open desktop session is untouched (the
  probe never sends RFB's ClientInit, which is when QEMU would apply its sharing policy).
- Scrape job `probes-access`, every 60 seconds: each console probe makes pve01 start
  `qm vncproxy` (a Perl program, ~370 ms of CPU and ~120 MB for its lifetime), so once a
  minute per desktop is cheap, every 15 seconds wouldn't be.
- Alert `AccessPathDown`: a probe failing for 3 minutes **while the machine itself is up**
  (`up{job="workstations"} == 1`). A machine that is down entirely is TargetDown's;
  reboots and hibernation (the target drops out within about a minute and a half) don't
  fire. ServiceProbeFailed now covers only the fixed service list (`job="probes"`).
- Dashboard: an "Access paths" timeline in the Lab overview's Workstations row. The
  "Service checks" panel is scoped to `job="probes"` (it queried every `probe_success`,
  so the per-machine rows showed up there too on the first render).

## Verification

With a throwaway blackbox container on mgmt01 using the same modules:

```
ssh_banner  10.10.10.36:22     probe_duration_seconds 0.0042  probe_success 1
ssh_banner  10.10.10.35:22     probe_duration_seconds 0.0051  probe_success 1
rfb_banner  10.10.10.10:6136   probe_duration_seconds 0.3700  probe_success 1   (ws36, running)
rfb_banner  10.10.10.10:6131   probe_duration_seconds 0.0238  probe_success 0   (ws31, hibernated: clean refusal)
ssh_banner  10.10.10.31:22     probe_duration_seconds 5.0042  probe_success 0   (ws31, hibernated)
```

On pve01 afterwards: 0 failed units, no `qm vncproxy` left running, each probe's unit
"Deactivated successfully". On ws36, sshd logged one line per probe:
`Connection closed by 10.10.10.6 port 45486 [preauth]`.

## Prevention

A user-facing path that exists per machine gets a per-machine probe from the same record
that creates the machine (`lab-metrics`), so new machines are covered without anyone
editing a list. The alert is keyed on "machine up, path down", which is the case a person
can act on (restart sshd, look at the relay) rather than a duplicate of TargetDown.
