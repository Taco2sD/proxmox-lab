---
id: KB-0029
title: "The DHCP server's DNS updates were REFUSED for names clients had registered before"
status: fixed
found_by: build
signal: "nsupdate: REFUSED"
found: 2026-11-06
resolved: 2026-11-06
severity: medium
hosts: [dc01]
components: [ad-dns, dhcp, samba-ad]
patterns: [two-writers-one-object]
commits: [9b2bd0c]
related: [KB-0030]
---

# KB-0029: The DHCP server's DNS updates were REFUSED for names clients had registered before

## Symptom

After moving DHCP to dc01 with a hook that registers A and PTR records (GSS-TSIG as svc-dhcp-dns), updates for some hosts were refused.

## How it was found

Testing the DHCP hook's nsupdate for each workstation.

## Root cause

In AD-integrated DNS, a name object (dnsNode) is owned by whichever account created it, and that includes empty tombstoned objects left after the records were deleted. The workstations had registered themselves earlier, so their machine accounts owned the names and the DHCP service account wasn't allowed to write.

## Fix

Single writer: the DHCP server registers DNS, clients never do (SSSD `dyndns_update = False`, in `ansible/roles/ad_join`). The stale dnsNode objects were deleted with `ldbdel` on dc01 so the service account could recreate them (`ansible/roles/dhcp_server` has the hook).

## Verification

nsupdate from the hook succeeded for every reserved host; forward and reverse lookups answered.

## Prevention

Reservations are the single source of truth for addresses and DNS follows from them (README: design decisions).
