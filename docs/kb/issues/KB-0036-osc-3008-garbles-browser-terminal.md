---
id: KB-0036
title: "Browser terminal filled with start=...;machineid=... on every prompt"
status: fixed
found_by: build
signal: "Escape-code text in Guacamole's terminal"
found: 2026-11-06
resolved: 2026-11-06
severity: low
hosts: [workstations]
components: [guacamole, ansible-pull]
patterns: [upstream-default-changed]
commits: [151b64b]
related: []
---

# KB-0036: Browser terminal filled with start=...;machineid=... on every prompt

## Symptom

Every Enter in the browser terminal printed a line like `start=...;machineid=...;user=...`.

## How it was found

First use of the portal's Connect button.

## Root cause

systemd's new profile script `/etc/profile.d/80-systemd-osc-context.sh` prints OSC 3008 "context" escape codes around each prompt. Guacamole's terminal doesn't know them and shows them as text.

## Fix

`dpkg-divert` the script on workstations, so package upgrades respect its removal (`ansible/roles/base/tasks/main.yml`).

## Verification

Clean prompts in the browser terminal.

## Prevention

New distro releases add profile hooks; test the browser terminal after an image build.
