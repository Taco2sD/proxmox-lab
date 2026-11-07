---
id: KB-0013
title: Forgotten browser tabs keep polling the lab all day (a Guacamole desktop and an old Proxmox UI)
status: open
found_by: investigation
signal: lab-console refusals in pve01's journal; 404s for /api2/json/* in mgmt01's nginx log
found: 2026-11-07
severity: low
hosts: [pve01, mgmt01]
components: [guacamole, console-relay, portal, nginx, sign-in-gate]
patterns: [client-retry-loop]
commits: []
related: [KB-0001]
---
## Symptom

Two kinds of steady background traffic that nobody is looking at:

1. **A Guacamole tab on a sleeping machine's desktop.** Signed in as the throwaway test
   account `ztest`, it has reconnected to "ws31 desktop" every few seconds since ws31 was
   hibernated at 18:22 (3,745 connections in Guacamole's log). A second staff account's tab
   does the same, less often, for ws34.
2. **A Proxmox UI tab pointed at the portal's name.** It polls `/api2/json/cluster/tasks`
   and `/api2/json/cluster/resources` on lab.radicallydecent.com about every 2 seconds. The
   portal answers 404 each time. It is a Proxmox UI page loaded back when
   lab.radicallydecent.com still led to pve01's port 8006, and never reloaded.

```
# mgmt01 /var/log/nginx/access.log, 2026-11-07 (requests arrive via the VPS and pve01's relay)
10.10.10.10 - - [07/Nov/2026:00:56:39 +0100] "GET /api2/json/cluster/tasks HTTP/1.1" 404 22 "https://lab.radicallydecent.com/" "Mozilla/5.0 (Windows NT 10.0; ...) Chrome/133..."
10.10.10.10 - demo [07/Nov/2026:22:19:20 +0100] "GET /api2/json/cluster/resources HTTP/1.1" 404 22 "https://lab.radicallydecent.com/" "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ..."
  38,082 such requests that day: 29,874 from a Mac (all day, still going), 8,210 from a
  Windows Chrome (until 05:30); ~1,800 an hour
```

## How it was found

Incidentally, while finding the cause of [KB-0001](KB-0001-console-relay-failed-units.md):
Guacamole's log named the account and connection behind the relay's refusals, and the tail
of nginx's access log showed the Proxmox API calls next to it.

## Root cause

Clients that retry or poll forever, against something that's switched off (a hibernated
VM) or no longer there (the Proxmox UI moved to pve.radicallydecent.com). The lab can't
end either from the server side. Guacamole's JSON-auth sessions live until their login
expires (8 hours), and the old Proxmox tab gets a cheap 404 and simply asks again.

## Fix

None on the server side yet: status open. **Action for a person:** close the forgotten
tabs: the Guacamole tab(s) on ws31's and ws34's desktops, and any tab showing the Proxmox
UI at `https://lab.radicallydecent.com/` (on the Mac, and on the Windows machine if
it's still open). The Proxmox UI lives at `https://pve.radicallydecent.com/`.

The ztest Guacamole loop stops by itself when its login expires (about 00:22 UTC on
2026-11-08). Since KB-0001, each attempt costs pve01 a PID-file check, not a `qm` start.

## Verification

After the tabs are closed:
- `journalctl -u 'lab-console@*' --since -10min -o cat | grep -c 'is not running'` on
  pve01 is 0;
- `tail -n 2000 /var/log/nginx/access.log | grep -c '/api2/json/'` on mgmt01 is 0.

## Prevention

- Ideas, not done: the portal could answer `/api2/` on the lab name with a redirect to
  pve.radicallydecent.com (a stale Proxmox tab would then load the real UI). Guacamole
  logins could carry only machines that are awake.
- Signals worth graphing if this recurs: the rate of the relay's refusals (a textfile
  counter on pve01), and nginx 404s by path on mgmt01.
