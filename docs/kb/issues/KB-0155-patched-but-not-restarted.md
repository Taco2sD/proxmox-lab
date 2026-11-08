---
id: KB-0155
title: Security updates installed but services kept running the old code, and nothing showed it
status: fixed
found_by: investigation
signal: needrestart -b after mgmt01's 76 security updates
found: 2026-11-07
resolved: 2026-11-08
severity: medium
hosts: [mgmt01, pve01, dc01, workstations]
components: [patching, node-exporter, docker, proxmox-ve]
patterns: [patched-but-not-restarted, monitoring-blind-spot]
commits: [b09efe3, 00fe16c]
related: [KB-0005, KB-0156]
---
## Symptom

After roles/patching installed mgmt01's 76 pending security updates
([KB-0005](KB-0005-no-automatic-security-updates.md)), apt and the dashboards said
"0 pending", but `containerd`, `dbus` and `docker` (and through docker the portal's
Guacamole, Grafana and Prometheus) were still running the replaced libraries. Overnight
the same happened on pve01: unattended-upgrades installed a zlib1g security update at
06:11, and 19 services (every Proxmox daemon, `ssh`, `journald`, `systemd` itself) plus
the mgmt01 container kept the old zlib in memory.

## How it was found

Noticed while finishing KB-0005: restarting what the update touched on mgmt01 stopped
short of dockerd (it bounces every container), which raised the question of how anyone
would know what is still on old code. Nothing in the monitoring could tell: the
`apt_upgrades_pending` metric only covers packages not yet installed.

```
mgmt01$ needrestart -b
NEEDRESTART-SVC: containerd.service
NEEDRESTART-SVC: dbus.service
NEEDRESTART-SVC: docker.service
pve01$ grep -A2 'Start-Date: 2026-11-08  06' /var/log/apt/history.log
Commandline: /usr/bin/unattended-upgrade
Upgrade: zlib1g:amd64 (1:1.3.dfsg+really1.3.1-1+b1, 1:1.3.dfsg+really1.3.1-1+deb13u1)
```

## Root cause

Updating a package replaces files; running processes keep the old mapping until they
restart. Automatic security updates install but deliberately don't restart (and must not
here, [KB-0156](KB-0156-needrestart-ubuntu-auto-restart.md)), so "patched" and "protected"
drift apart with every update, and the drift was invisible.

## Fix

roles/patching now installs needrestart in list mode on every machine and runs
`/usr/local/libexec/lab-restart-metrics` every 15 minutes (lab-restart-metrics.timer). It
runs `needrestart -b -r l` and writes node_exporter textfile metrics:
`needrestart_service{unit}`, `needrestart_services`, `needrestart_containers`,
`needrestart_sessions`, `needrestart_kernel_status` (0 unknown/container, 1 current,
2 ABI-compatible update, 3 newer version), `needrestart_kernel_info{running,expected}`,
`needrestart_scan_success`, `needrestart_last_run_timestamp_seconds`. New alert
[ServicesNeedRestart](../runbooks/ServicesNeedRestart.md) (warning after 24 h, one per
host with a count). The Machine dashboard lists the units and the workstation table has
a "Restart" column.

Nothing was restarted as part of this fix: what to restart, and when, stays a person's
call (the runbook says what each restart interrupts here).

## Verification

Applied by hand exactly as the role does on mgmt01, dc01, pve01, ws35 and ws36:

```
mgmt01: needrestart_services 3   (containerd, dbus, docker)   kernel_status 0 (container)
pve01:  needrestart_services 19  needrestart_containers 1 (LXC 106)  kernel_status 1
dc01, ws35, ws36: needrestart_services 0, kernel_status 1
```

2026-11-08, with the owner's go-ahead: pve01's 18 services restarted one at a time (running
workstations kept running) and mgmt01's container rebooted (`pct reboot 106`). Afterwards
`needrestart_services` is 0 on both and ServicesNeedRestart cleared. The reboot exposed two
follow-ups: Prometheus and blackbox stayed exited after the container came back (started
again with `docker compose up -d`; cause not yet known), and ReconcilerStopped fired for
about two minutes until the reconciler's first run after boot.

All five report `needrestart_scan_success 1`; node_exporter on mgmt01 exports the 9
series. Installing needrestart restarted nothing (no Stopping/Restarting lines in the
journal).

## Prevention

The ServicesNeedRestart alert puts a deadline on the drift, and the
[patched-but-not-restarted](../patterns/patched-but-not-restarted.md) pattern page says
how to read it. Still open as of this page: mgmt01's dockerd/containerd/dbus and pve01's
19 services need planned restarts (or a reboot of each host).
