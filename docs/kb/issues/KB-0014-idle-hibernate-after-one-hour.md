---
id: KB-0014
title: Staff machines hibernated after only one hour without a session
status: fixed
found_by: user
signal: User report - "one hour idle is enough to hibernate a ws VM. That's way, way too short."
found: 2026-11-07
resolved: 2026-11-07
severity: medium
hosts: [mgmt01, workstations]
components: [portal-worker, portal]
patterns: []
commits: [3301016]
related: []
---
## Symptom

Staff workstations went to sleep (hibernate: suspended to disk) after 60 minutes without an SSH
connection or an active desktop session. People returning after a meeting found their machine
asleep.

## How it was found

Reported by the lab's owner.

## Root cause

`idle_hibernate_minutes: 60` in ansible/group_vars/all.yml: chosen to free memory for new machines
(admission is by memory), too aggressive for how people actually use a workstation.

## Fix

`idle_hibernate_minutes: 2880` (48 hours). My lab's text and the worker's log say the limit in hours
(`2880 minutes` would have been unreadable).

## Verification

The reconciler deployed 3301016; `grep idle_hibernate /opt/proxmox-lab/ansible/group_vars/all.yml`
on mgmt01 showed 2880. Machines already hibernated (ws31 to ws34) stay asleep until someone wakes
them.

## Prevention

The value lives in one place (ansible/group_vars/all.yml) and is shown to people on My lab, so the
policy is visible where it applies. The Lab overview's "Memory budget" panel shows whether a longer
idle time is pushing the lab against its memory budget.
