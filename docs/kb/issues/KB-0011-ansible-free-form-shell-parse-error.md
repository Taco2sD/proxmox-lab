---
id: KB-0011
title: A shell task with backslash continuations failed Ansible's argument parsing
status: fixed
found_by: build
signal: 'ansible-playbook: "failed at splitting arguments, either an unbalanced jinja2 block or quotes"'
found: 2026-11-07
resolved: 2026-11-07
severity: low
hosts: [pve01]
components: [pve-exporter]
patterns: [ansible-parsing-gotcha]
commits: [3d34679]
related: []
---
## Symptom

The first test run of ansible/site.yml with the monitoring roles stopped before doing anything:
"Error loading tasks: failed at splitting arguments, either an unbalanced jinja2 block or quotes",
pointing at the token task in roles/pve_monitoring.

## How it was found

While building the monitoring: the first run of the playbook from a copy of the working tree on
mgmt01 (ansible-lint had passed).

## Root cause

The task used the free-form syntax (`ansible.builtin.shell: |`). Ansible splits free-form arguments
itself to find `key=value` options, and a script with backslash line continuations inside quoted
arguments (`--comment "..." \`, a `printf '...\n...'`) doesn't survive that splitter.

## Fix

The script moved under the `cmd:` key, with `executable: /bin/bash` beside it. Ansible passes `cmd`
to the shell untouched.

## Verification

The next run completed: pve01 ok=23 changed=9 failed=0; the token was created and the exporter
answered `/pve` with Proxmox's metrics.

## Prevention

New shell tasks use the `cmd:` form. Changed roles run against a real host before they're pushed:
lint can't see run-time parsing.
