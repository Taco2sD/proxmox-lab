---
id: KB-0102
title: Visitors' workstations can reach the hypervisor's root SSH (password login allowed) and Proxmox UI
status: open
found_by: review
signal: "pre-mortem: TCP connects from ws35 to 10.10.10.10:22 and :8006; sshd -T on pve01"
found: 2026-11-07
severity: high
hosts: [workstations, pve01, dc01, mgmt01]
components: [proxmox-ve, workstations, portal, samba-ad, node-exporter]
patterns: [flat-network-trust]
commits: []
related: []
---
## Symptom

The portal gives people from outside (visitors, interviewers) a shell on a workstation.
Every workstation sits on the same flat 10.10.10.0/24 as the management plane, with no
filtering between them. From a visitor's machine you can reach:

- pve01's SSH as **root with password authentication** (the root account has a password,
  since it's also the Proxmox UI login), and the Proxmox UI/API on 8006
- dc01's and mgmt01's SSH, and every machine's node_exporter on 9100

There's no rate limiting (no fail2ban, no `MaxStartups` tuning), so the root password is
open to unlimited guessing from inside the lab.

## How it was found

From ws35 (a guest workstation), through the guest agent on pve01:

```
10.10.10.10:22 open      10.10.10.10:8006 open     10.10.10.5:22 open
10.10.10.6:22 open       10.10.10.10:9100 open     10.10.10.36:22 open
10.10.10.6:9090 closed   10.10.10.6:3000 closed    (Prometheus/Grafana bind 127.0.0.1)
```

On pve01:

```
$ sshd -T | grep -E "^(passwordauthentication|permitrootlogin)"
permitrootlogin yes
passwordauthentication yes
$ passwd -S root | cut -d" " -f1-2
root P
$ dpkg -l fail2ban | grep -c ^ii
0
```

dc01 has `passwordauthentication yes` (root: prohibit-password). The PVE firewall is on
(`cluster.fw enable: 1`) but with `policy_in: ACCEPT`, and no guest VM has a firewall file.

## Root cause

The network grew from a single-user lab, where everything on 10.10.10.0/24 was trusted, into
a multi-user one (the portal, the welcome page), but the trust model didn't change with it.
Only the internet edge (the VPS gate, the tunnel's nft rules) was hardened.

## Fix

Proposed in PLAN-0005, cheapest first, not applied:

1. pve01: `PasswordAuthentication no` and `PermitRootLogin prohibit-password` in an sshd
   drop-in, managed by a pve01 role. Key logins (the lab key, svc-runner) are unaffected.
   Check first that nothing logs in to pve01 by password (`journalctl -u ssh | grep
   "Accepted password"`).
2. Proxmox firewall for the guest VMs (a security group in `cluster.fw`, applied to every
   workstation by OpenTofu): outbound to 10.10.10.10/32, 10.10.10.6/32 and 10.10.10.5/32
   only on the ports workstations need (DNS 53, Kerberos 88/464, LDAP(S) 389/636, NTP 123,
   HTTPS 443 to mgmt01; DHCP is broadcast). Inbound only from mgmt01 (Guacamole SSH,
   Prometheus 9100) and the gateway.
3. Later: workstations on their own VLAN/bridge, with mgmt01 and dc01 as the only routed
   services.

## Verification

Not fixed yet. Done when the same connect test from a guest workstation shows 22/8006 on
pve01 closed, logins and ansible-pull on workstations still work, and Guacamole still
connects.

## Prevention

Treat any machine a non-admin can log in to as untrusted, and write the allowed flows down
as firewall rules in git. See [flat-network-trust](../patterns/flat-network-trust.md).
