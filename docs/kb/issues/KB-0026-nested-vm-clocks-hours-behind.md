---
id: KB-0026
title: "Nested VMs woke up hours behind; apt refused 'Release file is not valid yet'"
status: mitigated
found_by: investigation
signal: "apt: Release file is not valid yet"
found: 2026-11-05
resolved: 2026-11-06
severity: medium
hosts: [dc01, mgmt01, workstations]
components: [time-sync]
patterns: [nested-virtualization-quirks, default-doesnt-fit]
commits: [9b2bd0c]
related: [KB-0031]
---

# KB-0026: Nested VMs woke up hours behind; apt refused "Release file is not valid yet"

## Symptom

On 2026-11-05 the guests' clocks were about 4.8 hours behind real time. apt refused repository metadata "not valid yet", and Kerberos would refuse anything over 5 minutes off.

## How it was found

Noticed when apt failed on a workstation the morning after.

## Root cause

Not fully established. The Windows host had slept for only 22 seconds, so a long host sleep doesn't explain it; the suspect is the nested guests' clock running slow or freezing with the hypervisor. Either way chrony's default `makestep 1 3` only steps the clock in the first three updates after start, so a running guest slewed back very slowly.

## Fix

`makestep 1 -1` everywhere (step whenever off by more than a second), with dc01 as the time source (`ansible/roles/base/tasks/main.yml` for workstations).

## Verification

Clocks stepped back into line at the next chrony update; the monitoring's clock-offset panel shows 0 on every host since it exists.

## Prevention

The ClockSkew alert now fires at 0.5 s offset for 5 minutes, long before Kerberos breaks.
