---
id: KB-0058
title: "Remote desktop over RDP couldn't serve the GNOME desktop through Guacamole"
status: accepted
found_by: investigation
signal: "Guacamole RDP connection fails"
found: 2026-11-07
severity: medium
hosts: [workstations, mgmt01]
components: [desktop, guacamole]
patterns: []
commits: [8f0a91f, 733e998, eefb888]
related: [KB-0056]
---

# KB-0058: Remote desktop over RDP couldn't serve the GNOME desktop through Guacamole

## Symptom

GNOME Remote Login (RDP) and xrdp both failed as the desktop path through Guacamole.

## How it was found

Building the Desktop button.

## Root cause

GNOME Remote Login hands the client over with RDP server redirection, which guacd doesn't support; xrdp can't serve GNOME 50 (and light-locker blanked xrdp sessions, 8f0a91f).

## Fix

Not fixed: worked around by showing the VM's own console through Guacamole VNC (733e998, then the console relay in eefb888).

## Verification

The console path works, including GNOME's own login screen.

## Prevention

Revisit when guacd supports RDP redirection.
