---
id: KB-0104
title: A critical service that is stopped (not failed) raises no alert, and DHCP is never probed
status: open
found_by: review
signal: "pre-mortem: alerts.yml has no rule on node_systemd_unit_state state=active/inactive"
found: 2026-11-07
severity: medium
hosts: [dc01, pve01, mgmt01]
components: [alert-rules, dhcp, portal-relay, console-relay, time-sync, node-exporter]
patterns: [monitoring-blind-spot]
commits: []
related: [KB-0101]
---
## Symptom

`SystemdUnitsFailed` fires only for units in the **failed** state. A service that someone
stops, that isn't started after a reboot, or that systemd gave up on and that later went
`inactive` raises nothing. For several of the lab's key services, no other alert would catch
it either:

| Unit | Host | Caught by a probe or another alert? |
|---|---|---|
| `dnsmasq.service` (DHCP) | dc01 | **No.** New and rebooting machines get no address |
| `lab-portal-relay.socket` | pve01 | **No.** `TunnelDown` watches WireGuard, not the relay behind it, and the public probe stops at the VPS's sign-in gate |
| `lab-console.socket` | pve01 | **No.** My lab's Desktop button breaks |
| `chrony.service` | any | Only slowly, through `ClockSkew` once the clock has drifted |
| samba-ad-dc, nginx, pveproxy, wg-quick@lab, the portal worker | | Yes (probes, `TunnelDown`, `PortalWorkerStale`) |

The Lab overview's **Key services** panel shows all of them, but only to someone looking.

## How it was found

```
$ grep -c dnsmasq ansible/roles/monitoring/files/alerts.yml
0
$ grep -c 'state="inactive"' ansible/roles/monitoring/files/alerts.yml
0
```

The blackbox probes cover HTTPS, LDAPS, Kerberos and DNS, but not DHCP, the relay sockets
or the console port.

## Root cause

The failed-unit alert was taken to mean "services are healthy", but for long-running
services the meaningful state is "should be active and isn't".

## Fix

Proposed in PLAN-0002, not applied:

1. One rule, `KeyServiceDown`, driven by the same unit list as the dashboard panel
   (dnsmasq, samba-ad-dc, chrony, nginx, docker, the portal and its worker, pveproxy,
   pvedaemon, pve-cluster, wg-quick@lab, lab-console.socket, lab-portal-relay.socket) and
   scoped to the host each one belongs on. Expression:
   `node_systemd_unit_state{state="active",name=~"<list>"} == 0`, `for: 2m`, critical,
   with a runbook.
2. A DHCP probe. blackbox has no DHCP module, so use a small textfile check on mgmt01 (an
   `nmap --script broadcast-dhcp-discover` or `dhclient -1 -n` run in a network namespace),
   or treat `dnsmasq.service` active plus a lease file updated within 24 h as the signal.
3. A TCP probe of the console relay for one running guest (the 6000+VMID port, from mgmt01),
   as fix-console suggested.

## Verification

Not fixed yet. Done when `systemctl stop dnsmasq` on dc01 (in a quiet moment) fires
`KeyServiceDown` within 3 minutes, and it clears when the service is started again.

## Prevention

Alert on the desired state ("this must be active"), not only on the failure state. See
[monitoring-blind-spot](../patterns/monitoring-blind-spot.md).
