---
id: KB-0047
title: "Clones booted fine but never enrolled: systemd dropped the first-boot unit"
status: fixed
found_by: build
signal: "No lab-firstboot run; machine never joined AD"
found: 2026-11-07
resolved: 2026-11-07
severity: high
hosts: [workstations]
components: [golden-image]
patterns: [boot-ordering-race]
commits: [0d02cec]
related: [KB-0046]
---

# KB-0047: Clones booted fine but never enrolled: systemd dropped the first-boot unit

## Symptom

Clones booted to a login prompt but never fetched their join password or joined AD.

## How it was found

Clone stayed at 'created' in the portal.

## Root cause

lab-firstboot was ordered `After=cloud-final.service`, but cloud-final itself runs after `multi-user.target`, the target that wanted lab-firstboot. systemd found the ordering cycle and dropped the unit from the transaction (logged once at boot).

## Fix

Order it after `cloud-config` (the hostname is set by then) and make it `Type=simple` (0d02cec).

## Verification

Clones enrolled at first boot.

## Prevention

Check `journalctl -b | grep -i cycle` after changing boot-time units.
