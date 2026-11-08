---
id: KB-0002
title: SSSD's nss, pam and pac responder sockets sat failed on every workstation
status: fixed
found_by: monitoring
signal: SystemdUnitsFailed
found: 2026-11-07
resolved: 2026-11-07
severity: low
hosts: [workstations]
components: [sssd, workstations]
patterns: [conflicting-activation-modes]
commits: [f53d992]
related: []
---
## Symptom

On the first day of monitoring, every running workstation (ws35, ws36) reported three
failed units: `sssd-nss.socket`, `sssd-pam.socket` and `sssd-pac.socket`
("Control process exited, code=exited, status=17"). Logins worked; the failures were
noise that would hide a real SSSD failure among them.

## How it was found

The Machine dashboard's **Failed units** stat and table (node_exporter's systemd
collector, `node_systemd_unit_state{state="failed"}`), and the alert
[SystemdUnitsFailed](../runbooks/SystemdUnitsFailed.md) pending for ws35 and ws36 with
3 units each.

## Root cause

Two ways of starting the same SSSD responders were both switched on:

- `ansible/roles/ad_join/templates/sssd.conf.j2` has `services = nss, pam`: SSSD's
  monitor starts those responders itself, and adds `pac` because the domain uses the AD
  provider.
- Ubuntu's sssd 2.12.0 package enables socket activation for the same responders
  (`sssd-nss.socket` etc., `WantedBy=sssd.service`).

SSSD refuses to run a responder both ways. Each socket's
`ExecStartPre=/usr/libexec/sssd/sssd_check_socket_activated_responders -r nss` exits 17,
and the journal says so plainly:

```
Misconfiguration found for the 'nss' responder.
It has been configured to be socket-activated but it's still mentioned in the services' line of the config file.
```

The responders themselves ran fine (`sssd_nss`, `sssd_pam`, `sssd_pac` from the
monitor), which is why nothing visible broke.

## Fix

Keep the monitor-started responders (how every login has worked so far) and mask the
three sockets that can never start alongside them. `ansible/roles/ad_join/tasks/main.yml`:

- `systemd_service: name=sssd-{nss,pam,pac}.socket masked=true`
- reset their failed state, only when one is still marked failed (no change reported
  on later runs)

The alternative, dropping `services =` and relying on socket activation, would change
how every NSS and PAM request reaches SSSD for no gain on machines with a handful of
users. The `sudo`, `ssh` and `autofs` sockets aren't in `services =`, so they stay
socket-activated and healthy.

New clones get it at first boot (ad_join runs in the first `ansible-pull`); hibernated
machines get it on their first pull after waking.

## Verification

Applied by hand on ws35, then ws36 (the same steps the role runs):

```
== before: sssd-nss.socket sssd-pac.socket sssd-pam.socket
cleared
== after: failed=[]
sssd-nss.socket masked inactive   (pam, pac the same)
13663 /usr/libexec/sssd/sssd_nss --logger=files   (pam, pac, be running)
uid=20003(jrhodes) gid=10000(domain users) groups=10000(domain users),10003(ws-admins)
Online status: Online
su - jrhodes: ok
User jrhodes may run the following commands on ws35: (ALL : ALL) ALL
```

No SSSD warnings in the journal after the restart. sshd still resolved the AD user
("authenticating user jrhodes").

## Prevention

- The role now owns the socket state, so a package upgrade that re-enables the sockets
  is corrected on the next pull (masks override `WantedBy`).
- SystemdUnitsFailed catches any unit that fails on any machine within 5 minutes, and
  the Machine dashboard names it.
- Pattern: [conflicting-activation-modes](../patterns/conflicting-activation-modes.md).
  When a package ships both a daemon and socket units for the same thing, decide which
  one starts it and turn the other off explicitly.
