---
id: KB-0030
title: "Every Ansible run reported sssd.conf changed and restarted SSSD"
status: fixed
found_by: build
signal: "ansible-pull: changed=1 on every run"
found: 2026-11-06
resolved: 2026-11-06
severity: low
hosts: [workstations]
components: [sssd, ansible-pull]
patterns: [two-writers-one-object]
commits: [9b2bd0c]
related: [KB-0029, KB-0002]
---

# KB-0030: Every Ansible run reported sssd.conf changed and restarted SSSD

## Symptom

Each configuration run on a workstation showed sssd.conf as changed and restarted SSSD, so runs were never idempotent and logins blipped every 30 minutes.

## How it was found

Reading ansible-pull output on ws01.

## Root cause

`sssd.service` resets `/etc/sssd` and its files to `root:sssd`, group-readable, every time it starts. The role wrote `0600` root-only; the service changed it back; the next run "fixed" it again.

## Fix

The role writes `root:sssd 0640`, which is what the service enforces (`ansible/roles/ad_join`).

## Verification

Two consecutive runs reported no changes for sssd.

## Prevention

When a service manages its own files' ownership, match it instead of fighting it. KB-0002 is a later sssd issue found by monitoring.
