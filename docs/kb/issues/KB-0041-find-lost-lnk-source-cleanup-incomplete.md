---
id: KB-0041
title: "The first portal deletion left records behind"
status: fixed
found_by: build
signal: "Leftover MAC links after a delete"
found: 2026-11-06
resolved: 2026-11-06
severity: medium
hosts: [mgmt01]
components: [lab-cli, pxe-image-factory]
patterns: [upstream-default-changed]
commits: [8a1e0aa]
related: []
---

# KB-0041: The first portal deletion left records behind

## Symptom

After deleting a guest through the admin page, its MAC-address links in the install records were still there.

## How it was found

Checking every record after the first full deletion.

## Root cause

Clean-up matched symlinks by `lnk_source`, which `ansible.builtin.find` in ansible-core 2.20 no longer returns, so nothing matched.

## Fix

Match links by name (8a1e0aa). Workstations no longer have install records at all (golden image).

## Verification

A deletion removed the VM, AD accounts, DHCP reservation and lease, DNS records, install record and links.

## Prevention

Pin behaviour you depend on with a check that fails loudly when it returns nothing.
