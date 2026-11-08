---
id: KB-0001
title: Failed lab-console@ units pile up on pve01 while a browser keeps reconnecting to a sleeping machine
status: fixed
found_by: monitoring
signal: SystemdUnitsFailed
found: 2026-11-07
resolved: 2026-11-07
severity: medium
hosts: [pve01]
components: [console-relay, guacamole, portal]
patterns: [per-connection-unit-pileup, client-retry-loop]
commits: [15f0c00]
related: [KB-0013, KB-0007]
---
## Symptom

pve01 had 1,657 failed systemd units, then 1,849 an hour later, all of them
`lab-console@<n>-10.10.10.10:6131-10.10.10.6:<port>.service`. Each one's journal ended the
same way:

```
qm[716383]: VM 131 qmp command failed - VM 131 not running
lab-console[716383]: VM 131 not running
lab-console@999-...service: Main process exited, code=exited, status=255/EXCEPTION
lab-console@999-...service: Consumed 350ms CPU time, 119.7M memory peak.
```

## How it was found

The first scrape of pve01's node_exporter (systemd collector) after the monitoring went in.
The per-unit alert rule of the time fired once per unit, ~1,700 alerts at once, which is
[KB-0007](KB-0007-systemd-alert-storm.md). The Lab overview's "Firing alerts" stat read 1670.

## Root cause

Two things together:

1. **The relay's units are one per connection.** `lab-console.socket` has `Accept=yes`, so
   systemd starts a `lab-console@` instance for every TCP connection
   (`ansible/roles/pve_console/templates/lab-console.socket.j2`). An instance that exits
   non-zero stays loaded as a failed unit until someone runs `systemctl reset-failed`.
   Nothing did.
2. **A browser retried forever against a machine that is meant to be off.** ws31 (VM 131)
   was hibernated at 18:22. A Guacamole tab still open on its desktop kept reconnecting:
   Guacamole's client reconnects by itself after an upstream error, every few seconds, for
   as long as its login lasts. The portal's logins last a working day (`expires` = 8 h in
   `ansible/roles/portal/files/portal.py`: `guacamole_login`), on purpose, so Reconnect
   works. Each attempt reached pve01's relay, `qm vncproxy` failed because the VM wasn't
   running, and one more failed unit stayed behind: ~8 a minute, 3,570 in the day for VM
   131 (and 34 for VM 134, another staff account's open tab).

```
# pve01, during the loop
journalctl -u 'lab-console@*' --since -30min -o cat | grep -c 'VM 131 not running'   ->  232
# mgmt01, the Guacamole side
User "ztest" connected to connection "ws31 desktop".
User "ztest" disconnected from connection "ws31 desktop". Duration: 380 milliseconds
```

Each attempt also cost pve01 a Perl `qm` start: ~350 ms of CPU and ~120 MB peak memory,
to answer a question a PID file can answer.

## Fix

In `ansible/roles/pve_console`:

- `templates/lab-console@.service.j2`: `CollectMode=inactive-or-failed`. Instances are
  unloaded when they end, failed or not. What happened stays in the journal.
- `files/lab-console`: before starting `qm`, check whether the VM's QEMU process exists
  (`/var/run/qemu-server/<vmid>.pid` and `kill -0`). If it doesn't, log one clear line
  (`VM 131 is not running (hibernated or stopped); connection refused`) and exit 0.
  Refusing a screen that is switched off is the relay working as intended, so it isn't
  reported as a failure. Real faults (an unknown port, `qm` failing on a running VM) still
  exit non-zero.

**Not changed: the reconnect loop itself.** Portal logins use Guacamole's JSON
authentication, which has no server-side way to end a browser's session (only the browser
holds the session token), and the worker can't tell Guacamole to drop one connection. The
loop ends when the login expires: ztest's last login was 16:21:54 UTC, so it stops by
itself at about 00:22 UTC. Restarting Guacamole would end it sooner, but it would also end
everyone's sessions, so it wasn't done. Closing the tab ends it too (see
[KB-0013](KB-0013-stale-browser-tabs.md)).

## Verification

On pve01, after installing the unit and script as the role does (daemon-reload, then
`systemctl reset-failed 'lab-console@*'`):

```
systemctl list-units --failed --no-legend --plain | grep -c lab-console@   ->  0
journalctl -u 'lab-console@*' --since 22:19 -o cat | grep -c 'Failed with result'  ->  0
lab-console: VM 131 is not running (hibernated or stopped); connection refused
```

Prometheus: `count(node_systemd_unit_state{host="pve01",state="failed"} == 1)` returns
nothing (no failed units). The reconnect loop carried on throughout.

A running guest's screen still works. From mgmt01, a TCP connection to pve01:6136 (ws36)
answered `RFB 003.008`, the VNC handshake. A connection to 6131 (hibernated ws31) closed
cleanly.

## Prevention

- Socket-activated `Accept=yes` services in this repo get `CollectMode=inactive-or-failed`
  ([per-connection-unit-pileup](../patterns/per-connection-unit-pileup.md)).
- An expected refusal exits cleanly and says why; only real faults fail.
- `SystemdUnitsFailed` is now one alert per machine with a count
  ([KB-0007](KB-0007-systemd-alert-storm.md)), so the same kind of pileup shows up as
  one alert with a big number.
- Gap: with refusals no longer failing, the relay's own health isn't watched. A blackbox
  TCP probe of the console port of a running guest would watch it (suggested to the
  alert-rules owner).
- Open idea: the portal could stop offering hibernated machines' desktops in new logins'
  `others`. Today's loop comes from a tab opened while the machine was awake, so that
  wouldn't have prevented it.
