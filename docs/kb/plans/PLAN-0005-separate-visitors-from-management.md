---
plan: PLAN-0005
title: Separate visitors' workstations from the management plane
status: proposed
owner: unassigned
created: 2026-11-07
issues: [KB-0102]
patterns: [flat-network-trust]
components: [workstations, proxmox-ve, samba-ad, mgmt01, opentofu, portal]
---
## Goal

A person with a shell on a guest workstation can reach only the services workstations
need, and no management interface accepts a password from the lab network.

## Why

**Decision:** KB-0102 is accepted for the demo lab (2026-11-08): this plan is what production would need, not something to do now.

From ws35 today, pve01's root SSH (with password authentication on) and the Proxmox UI both
answer, with no throttling (KB-0102). The portal hands those shells to people outside the
team.

## Steps

- [ ] Check that nothing logs in to pve01 or dc01 by password:
      `journalctl -u ssh --since -30d | grep "Accepted password"` on each.
- [ ] An sshd drop-in on pve01 (`PasswordAuthentication no`, `PermitRootLogin prohibit-password`)
      and on dc01 (`PasswordAuthentication no`), each managed by a role. Test a key login in a
      second session before closing the first.
- [ ] A Proxmox firewall security group for workstations (in `cluster.fw`, attached by
      terraform/modules/workstation): outbound to dc01 for DNS 53, Kerberos 88/464,
      LDAP 389/636 and NTP 123, to mgmt01 on 443, and to the internet. Inbound only from
      mgmt01 (SSH for Guacamole, 9100 for Prometheus).
- [ ] Re-run the reachability test from a guest workstation: pve01:22/8006, dc01:22 and
      mgmt01:22 closed, with AD logins, ansible-pull, the activity beacon and Guacamole all
      still working.
- [ ] Later: a separate bridge or VLAN for workstations.

## Risks and rollback

- Locking yourself out of pve01: keep a root shell open while testing, and keep the
  Hyper-V console as the out-of-band path. Rollback is deleting the drop-in and running
  `systemctl reload ssh`.
- A rule that's too tight breaks workstation enrolment (the OTP over 443, the AD join).
  Turn the group on for one test workstation first. Rollback is detaching it from that NIC
  (`firewall=0`), which takes effect at once.

## Done when

The reachability test from a guest workstation shows only the allowed flows, a fresh
workstation enrols and configures itself with the firewall on, and Guacamole still
connects.
