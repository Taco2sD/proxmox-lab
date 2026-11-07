# Self-service workstations

A web page where a visitor picks a username and a role, and the lab builds them a
workstation: AD account, VM, network install, domain join, role, and a terminal in the
browser when it's ready. Every request goes through git, the same as a hand-made change.
Lab admins can delete any workstation from the portal, these and the fleet (ws01..04)
alike, and the deletion removes everything the lab created for it.

Code: `mgmt01/portal/` (web app, worker, pages, nginx and systemd config), deployed with
`lab portal` (`ansible/portal.yml`).

## The path of a request

```text
browser ──HTTPS──► VPS: lab.radicallydecent.com
                    │ sign-in gate (oauth2-proxy): the lab access account
                    │ HTTPS, certificate verified, through the WireGuard tunnel
                    ▼
                  pve01 relay (TCP only) ──► mgmt01:8443 (portal + terminal only)
                                               │
          portal.py (unprivileged) ──► request file ──► worker.py (root)
                                                          1. inventory/guests/<host>.yml
                                                          2. git commit + push
                                                          3. lab apply (one run per batch)
                                                          ▼
                      Ansible: AD user (OU=Guests) + computer account + DHCP reservation
                               + autoinstall record + one-time join password
                      OpenTofu: the VM (many in parallel)
                      PXE + autoinstall, first boot: ansible-pull, domain join, role
          ◄── progress (the page polls; the worker reads nginx's log)
          ◄── "Connect": Apache Guacamole opens SSH to the machine, already logged in
```

Typical timings: request to VM created about 1 minute, Ubuntu install about 5–6 minutes,
domain join and role about 1–2 minutes. About eight minutes in all.

## The page

Modelled on Microsoft Dev Box's developer portal: **New workstation** opens one form
(username, checked as you type; role), the dialog closes on **Create**, and a tile shows
the machine's status, the current step and a progress bar. When it's ready, **Connect**
opens a terminal in a new tab; the **⋯** menu has details (address, username, password),
a link for another device, and **Delete**.

There are no accounts. Each machine has a random secret token; the browser keeps it in
`localStorage` and sends it in a header (`X-Lab-Token`), never in a URL, so it never
appears in a log. Only a hash of it is stored. "Copy link for another device" puts it
after a `#`, which browsers don't send to servers.

## Decisions

**Batching instead of one OpenTofu state per machine.** OpenTofu holds its state lock
only while it creates or destroys VMs (about 35 seconds); installs and configuration run
afterwards, outside OpenTofu, in parallel. One run also creates or destroys many VMs at
once. So the worker takes every waiting request, makes one commit and runs one
`lab apply`. Requests that arrive during a run go into the next batch.

**One file per guest machine.** Requests live in `inventory/guests/<host>.yml`, not in
`workstations.yml`. Adding or removing a machine is adding or deleting one file, so
concurrent requests never conflict in git, the history reads as one commit per batch,
and the portal never adds to the hand-maintained file. The one edit it makes there is
deleting a fleet machine's line when an admin deletes that machine (below).

**Addresses come from slots.** Guest machines use slots 1–9: VM ID 13N, IP 10.10.10.3N,
MAC BC:24:11:00:00:3N. The portal accepts at most four guest machines at a time (pve01's
memory).

**Two processes, two privilege levels.** The web side (`portal.py`, user `labportal`)
can only reserve a username, drop a request file, and read status files. The worker
(`worker.py`, root) holds the git deploy key and runs `lab`, which holds the Proxmox API
token. A username is reserved by creating its password file with `O_EXCL`, so two
requests can't take the same name.

**The visitor gets an AD account.** `<username>` is created in `OU=Guests` (role
`ad_guest_users`) with RFC2307 attributes and a generated password, which is stored only
on mgmt01 (never in git). It is deliberately not put in the role's group (artists or
programmers): that would admit them on every machine of the role. Their machine admits
only them and `ws-admins`: the workstation reads its own `inventory/guests/<host>.yml`
from its git checkout and adds the owner to SSSD's `simple_allow_users`.

**Terminal: Apache Guacamole 1.6** (Docker on mgmt01), with JSON authentication only: no
database and no Guacamole accounts. For each **Connect**, the portal builds a login for
one SSH connection to the visitor's own machine, valid for 60 seconds: HMAC-SHA256
signed, then AES-128-CBC encrypted with a key shared only with Guacamole. Before opening
it, the page signs out any Guacamole session the browser still has, because Guacamole
would otherwise reuse that session and ignore the new login. Workstations accept SSH
passwords only from mgmt01's address, where Guacamole runs; everything else is key-only.
On HTTPS, Guacamole can sync the clipboard with the browser.

## Progress

The worker doesn't poll machines. It reads signals the lab already produces:

| Step | Signal |
|---|---|
| Request received | request file written |
| Committed to git | commit pushed |
| Identity ready | OpenTofu starts (Ansible's AD, DHCP and record work runs before it) |
| VM created | OpenTofu's `Creation complete` line for the machine |
| Installing Ubuntu | the installer fetches its autoinstall record (nginx access log, by the machine's IP) |
| Joining the domain | the installer fetches its one-time join password |
| Ready | the first configuration run finishes and requests `/lab-events/configured` (the last task in `ansible/local.yml`) |

The worker remembers its position in nginx's log, so a restart doesn't miss a step.

**Failures are reported, not waited out.** If the installer's one-time-password request
is refused, the build fails at once with that reason (the installer would otherwise sit
at "An error occurred" forever). A build with no new step for 20 minutes fails as
stalled. A failed machine that is reinstalled (`lab reimage`) picks up again: its
install-record fetch restarts the timeline.

## Admin page and removal

`/admin` lists every workstation in any state: the fleet from `workstations.yml` and the
guest machines, with each machine's last configuration run (every workstation reports
one about every 30 minutes). The lab's own machines (pve01, dc01, mgmt01) are not
workstations and aren't listed. They also can't be deleted by any request: the web side
and the worker both refuse them by name, and neither OpenTofu nor `lab prune` manages
anything outside the workstation inventory. Sign-in is a lab admin's own AD
account: the portal binds to dc01 over LDAPS (Let's Encrypt certificate for
`dc01.lab.radicallydecent.com`, a name that exists only inside the lab) and admits
members of `ws-admins`, nested groups included. The password is never stored; a signed,
HttpOnly, SameSite=Strict cookie carries the session for 8 hours. Sign-in attempts are
rate-limited by nginx, and admin actions need a header only the page's own code sends.

An admin ticks one or more machines and presses **Delete** under the table; a warning
lists every machine about to be destroyed and says it can't be undone. All of them go in
one batch: one commit, one `lab apply`, one `lab prune`. An owner deletes only their own
machine, from its tile. Either way the path is the build in reverse, and the admin page
shows each machine's step live:

1. the request is queued, and the machine leaves the inventory (its file in
   `inventory/guests/`, or a fleet machine's line in `workstations.yml`, checked to
   parse to the same inventory minus that machine) in a commit that names who deleted it
   ("remove ws03 (by admin jrhodes)"),
2. `lab apply`: OpenTofu destroys the VM and its disk,
3. `lab prune`: the owner's AD user and the computer account, the DHCP reservation, the
   DHCP lease (released with `dhcp_release`, so the DHCP hook deletes the A and PTR
   records at once instead of when the lease would have expired), and the autoinstall
   record, MAC link and one-time-password rule on mgmt01,
4. the portal's own status file and stored password.

If the VM can't be destroyed, its accounts and records are left alone and the machine
shows as failed; deleting it again runs the whole removal again, skipping what's done.

## Exposure

`lab.radicallydecent.com` is the portal and `/guacamole/`; `pve.radicallydecent.com` is
the Proxmox UI. Both sit behind the VPS's sign-in gate (one 12-hour session for both),
and both hops behind it are TLS with verified certificates. The tunnel's firewall on
pve01 admits only the Proxmox UI and the portal relay. mgmt01's internet-facing port
(8443) serves the portal and the terminal only; autoinstall records, one-time passwords
and the ready signal exist only on its lab-facing port (443). See [vps/](../vps/README.md).
