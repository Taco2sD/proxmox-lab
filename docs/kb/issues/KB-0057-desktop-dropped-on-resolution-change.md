---
id: KB-0057
title: "Browser desktop dropped whenever the screen resolution changed"
status: fixed
found_by: build
signal: "Desktop disconnects after resizing"
found: 2026-11-07
resolved: 2026-11-07
severity: low
hosts: [workstations]
components: [desktop, guacamole]
patterns: []
commits: [9516136]
related: [KB-0056]
---

# KB-0057: Browser desktop dropped whenever the screen resolution changed

## Symptom

The desktop session in the browser disconnected when GNOME changed resolution.

## How it was found

Testing the Desktop button.

## Root cause

guacd 1.6.0 doesn't negotiate a new framebuffer size over this VNC path and drops the connection.

## Fix

Desktops start at 1920x1080 via a fixed monitors.xml (9516136, `ansible/roles/desktop/files/monitors.xml`).

## Verification

Desktop sessions stayed connected.

## Prevention

Pinned resolution in the desktop role.
