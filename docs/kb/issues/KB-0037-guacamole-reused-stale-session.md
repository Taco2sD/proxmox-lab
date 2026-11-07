---
id: KB-0037
title: "A second Connect showed 'No recent connections' instead of the machine"
status: fixed
found_by: build
signal: "Guacamole home page with no connections"
found: 2026-11-06
resolved: 2026-11-07
severity: medium
hosts: [mgmt01]
components: [guacamole, portal]
patterns: [browser-session-state]
commits: [33ff44c, 55e7859, e9920d2]
related: [KB-0039, KB-0013]
---

# KB-0037: A second Connect showed "No recent connections" instead of the machine

## Symptom

Clicking Connect a second time opened Guacamole's home page saying "No recent connections".

## How it was found

Testing Connect twice in one browser.

## Root cause

Guacamole reused the browser's existing session and ignored the new signed login, whose connection list had expired.

## Fix

Connect links straight to the connection (33ff44c); the portal signs out the old Guacamole session before each connect (55e7859); logins are single-use, last a working day and carry all the owner's connections, so Reconnect works (e9920d2).

## Verification

Repeated Connect and Desktop clicks opened the right machine each time.

## Prevention

A long-lived session also means an abandoned tab keeps reconnecting; KB-0013 is that case.
