---
id: KB-0046
title: "First clones of the golden image never finished booting"
status: fixed
found_by: build
signal: "Clone stuck at boot waiting for the network"
found: 2026-11-07
resolved: 2026-11-07
severity: high
hosts: [workstations]
components: [golden-image]
patterns: [default-doesnt-fit, boot-ordering-race]
commits: [4597d95]
related: [KB-0047]
---

# KB-0046: First clones of the golden image never finished booting

## Symptom

Clones of the golden image hung during boot, waiting for the network.

## How it was found

First clone after the golden-image switch.

## Root cause

Proxmox's cloud-init network config names the NIC `eth0`. cloud-init can't rename the already-up `ens18`, and netplan then made boot wait for an `eth0` that never appears.

## Fix

The image does DHCP on any `en*` NIC itself and cloud-init networking is off; the DHCP reservation decides the address (4597d95).

## Verification

Clones reached the network and ran first boot; clone to configured in about 1-2 minutes.

## Prevention

Addresses come from DHCP reservations only; the image doesn't depend on interface names.
