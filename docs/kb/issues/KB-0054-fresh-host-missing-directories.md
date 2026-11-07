---
id: KB-0054
title: "Playbooks failed on a fresh host: copying into directories that didn't exist yet"
status: fixed
found_by: build
signal: "Ansible: copy into a missing directory failed"
found: 2026-11-07
resolved: 2026-11-07
severity: low
hosts: [mgmt01, dc01, pve01]
components: [lab-cli]
patterns: [fresh-host-assumptions]
commits: [e4a989c, 76c56ed]
related: []
---

# KB-0054: Playbooks failed on a fresh host: copying into directories that didn't exist yet

## Symptom

The runner role failed copying lablib into /usr/local/lib/lab, and bootstrap.yml failed writing the automation account's key into .ssh.

## How it was found

Running the roles against hosts that hadn't been configured by hand before.

## Root cause

Both tasks assumed a directory created earlier by hand.

## Fix

Create the directory first (e4a989c, `ansible/roles/runner/tasks/main.yml`; 76c56ed, `ansible/bootstrap.yml`).

## Verification

The roles applied to a clean host.

## Prevention

A playbook that only ever ran on a hand-built host hides these; test roles against a fresh machine.
