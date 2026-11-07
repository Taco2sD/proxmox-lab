---
id: KB-0059
title: "mstsc logins to GNOME Remote Login failed: 'Could not find user in SAM database'"
status: fixed
found_by: investigation
signal: "RDP handover rejected"
found: 2026-11-05
resolved: 2026-11-05
severity: low
hosts: [windows-host, workstations]
components: [desktop]
patterns: [browser-session-state]
commits: []
related: [KB-0058]
---

# KB-0059: mstsc logins to GNOME Remote Login failed: "Could not find user in SAM database"

## Symptom

Connecting from Windows' Remote Desktop client to the first Ubuntu desktop VM failed after the first authentication step.

## How it was found

Logging in to the lab's first desktop VM from the Windows host.

## Root cause

With NLA, mstsc reused the saved credentials after GNOME's server redirection instead of the one-time credentials the handover daemon issued.

## Fix

`use redirection server name:i:1` in the client's default RDP settings makes mstsc use RDSTLS, which takes the redirected credentials. A client-side setting, not in the repo.

## Verification

The plain mstsc login reached the desktop.

## Prevention

The same redirection mechanism is why Guacamole can't serve GNOME over RDP (KB-0058).
