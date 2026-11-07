---
id: KB-0103
title: The Windows host has a pending servicing reboot that would take the whole lab down at an unplanned moment
status: open
found_by: review
signal: 'pre-mortem: registry key Component Based Servicing RebootPending exists on the Windows host'
found: 2026-11-07
severity: medium
hosts: [windows-host, pve01]
components: [windows-host, proxmox-ve, time-sync]
patterns: [unmanaged-lower-layer]
commits: []
related: [KB-0100]
---
## Symptom

Everything in the lab runs inside one Hyper-V VM (pve01) on the Windows 11 PC. Windows
Update reboots that PC on its own schedule, which restarts every server and workstation at
once. Nothing in the repo manages, or even watches, the Windows layer.

## How it was found

Read-only checks on the host:

```
pending reboot (CBS): True          # Component Based Servicing\RebootPending
pending reboot (WU):  False
NoAutoRebootWithLoggedOnUsers = 1   # policy: no forced reboot while someone is signed in
ActiveHoursStart = 9, ActiveHoursEnd = 3
LastBootUpTime: 2026-11-05 11:44
Get-VM pve01: AutomaticStopAction Save, AutomaticStartAction StartIfRunning
```

## Root cause

The host is a personal workstation, not a managed hypervisor. It installs updates whenever
Windows decides. The policy `NoAutoRebootWithLoggedOnUsers` stops forced reboots while
someone is signed in. Signed out, Windows may reboot outside active hours (03:00–09:00).
Either way, the pending servicing reboot happens at the next restart of any kind, including
one done in a hurry. When it happens, Hyper-V saves pve01's memory and restores it
afterwards. The nested guests then wake with clocks minutes or hours behind (a known effect
here; chrony's `makestep 1 -1` repairs it), and the WireGuard tunnel and Guacamole sessions
drop.

## Fix

Proposed in PLAN-0001, not applied (the user's machine, the user's call):

1. Before the interview on Tue 2026-11-10: reboot the PC deliberately at a chosen time, then
   watch the lab come back (dashboards: TargetDown, ClockSkew, TunnelDown clear). That
   also tests the cold-start path.
2. Pause Windows Update until after the interview (Settings → Windows Update → Pause, 1–2
   weeks).
3. For the longer term: show host reboots in monitoring. `node_boot_time_seconds` on pve01
   only moves if pve01 itself restarts, and a Hyper-V save/restore doesn't restart it, so
   alert on a clock jump instead (`ClockSkew`, or `changes(node_timex_offset_seconds[10m])`).

## Verification

Not fixed yet. Done when the PC has rebooted on purpose, the lab is green afterwards, and
updates are paused through 2026-11-11.

## Prevention

The layer under a managed system needs at least an owner, a maintenance window and a
signal. See [unmanaged-lower-layer](../patterns/unmanaged-lower-layer.md).
