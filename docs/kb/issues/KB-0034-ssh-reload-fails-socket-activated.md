---
id: KB-0034
title: "Configuration runs failed after an SSH policy change"
status: fixed
found_by: build
signal: "ansible-pull failed: systemctl reload ssh"
found: 2026-11-06
resolved: 2026-11-06
severity: medium
hosts: [workstations]
components: [ansible-pull]
patterns: [upstream-default-changed]
commits: [4d4bf0a]
related: [KB-0002]
---

# KB-0034: Configuration runs failed after an SSH policy change

## Symptom

After the role changed sshd's configuration, the handler `systemctl reload ssh` failed and the run failed.

## How it was found

ansible-pull output on a workstation.

## Root cause

Ubuntu starts `ssh.service` on demand through `ssh.socket`. When nobody is connected the service isn't running, and reloading a stopped service is an error.

## Fix

`systemctl try-reload-or-restart ssh` (4d4bf0a, `ansible/roles/ad_join`).

## Verification

Runs passed with and without an SSH session open.

## Prevention

Check whether a unit is socket-activated before writing its handler. KB-0002 is another socket-activation surprise.
