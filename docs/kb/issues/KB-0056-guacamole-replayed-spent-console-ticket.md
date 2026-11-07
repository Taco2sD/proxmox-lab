---
id: KB-0056
title: "Desktop Reconnect never worked: Guacamole replayed a spent one-time console ticket"
status: fixed
found_by: build
signal: "Desktop: reconnect fails, connection closed"
found: 2026-11-07
resolved: 2026-11-07
severity: medium
hosts: [pve01, mgmt01]
components: [guacamole, console-relay, desktop]
patterns: [client-retry-loop]
commits: [2726d66, eefb888]
related: [KB-0001, KB-0057]
---

# KB-0056: Desktop Reconnect never worked: Guacamole replayed a spent one-time console ticket

## Symptom

The Desktop button worked once; Guacamole's Reconnect, and its automatic reconnect after a dropped connection, always failed.

## How it was found

Testing Reconnect on a desktop machine.

## Root cause

Desktops were reached with Proxmox's one-time console tickets (API vncproxy), valid once and for seconds. Every reconnect replayed the spent ticket. Pre-loading Guacamole (2726d66) only fixed the first connect.

## Fix

pve01's console relay: lab-console.socket accepts connections from mgmt01 only and runs `qm vncproxy` per connection with a shared secret (eefb888, `ansible/roles/pve_console`).

## Verification

Reconnect and automatic reconnects reached the desktop again.

## Prevention

A fixed endpoint that reconnects safely. Its per-connection units later piled up as failures when a tab kept reconnecting to a hibernated VM (KB-0001).
