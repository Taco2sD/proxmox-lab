---
id: KB-0031
title: "First boot and later runs disagreed about the machine's AD groups"
status: fixed
found_by: build
signal: "Wrong or missing role on first boot"
found: 2026-11-06
resolved: 2026-11-06
severity: medium
hosts: [workstations]
components: [ansible-pull, samba-ad]
patterns: [upstream-default-changed]
commits: [9b2bd0c]
related: []
---

# KB-0031: First boot and later runs disagreed about the machine's AD groups

## Symptom

A freshly joined workstation sometimes got no catalogue role on its first run, and the right one on the next.

## How it was found

Reimaging ws03 and comparing first-run and second-run output.

## Root cause

The role wrote a local fact (`ad.fact`) and re-ran `setup` mid-play to read it. In ansible-core 2.20 refreshing local facts mid-play is unreliable, and the old fact names are deprecated.

## Fix

The role runs the AD lookup (`memberOf` of the machine account) as a command and keeps the result in one variable, `ad_groups` (`ansible/roles/ad_join`; `ansible/local.yml` loops over it).

## Verification

A reimaged ws03 got role-programmer on its first run.

## Prevention

Don't round-trip data through facts within one play; register it.
