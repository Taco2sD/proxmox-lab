# Self-service workstations

A web page where a visitor picks a username and a role, and the lab builds them a
workstation: AD account, a clone of the golden image, domain join, role, and a terminal
in the browser when it's ready. Lab admins see every workstation, fleet and guest, on
an admin page, delete any of them with a full clean-up, and see everything the lab did.

Code: `ansible/roles/portal/` (web side, worker, pages) on top of the runner
(`ansible/roles/runner/`: `lab` and `lablib.py`). Deployed with the servers
(`ansible/site.yml`).

## Guests are runtime records, not code

The fleet is in git (`inventory/workstations/`). Portal machines are not: each is a
record on mgmt01 (`/var/lib/lab/guests/<host>.json`) with its own OpenTofu state
(`/var/lib/lab/tofu/guest-<host>.tfstate`). That's how Microsoft Dev Box and Coder treat
workstations people request: the definitions are code (here `catalog/` and
`terraform/modules/workstation`), the instances live in a control plane. It means
visitors' names never go into a public repository, the release branch only moves for
real changes, and builds run independently and in parallel.

## The path of a request

```text
browser ──HTTPS──► VPS: lab.radicallydecent.com
                    │ sign-in gate (oauth2-proxy): the lab access account
                    │ HTTPS, certificate verified, through the WireGuard tunnel
                    ▼
                  pve01 relay (TCP only) ──► mgmt01:8443 (portal + terminal only)
                                               │
          portal.py (unprivileged) ──► request file ──► worker.py (root): checks,
                                                         guest record, operation
                                                          │ systemd-run lab-op-<id>
                                                          ▼
                                  lab guest create ws-<user>
                                   ├─ ansible/identity.yml (this host only): AD computer
                                   │  account in role-<role>, the owner's AD account and
                                   │  managedBy, DHCP reservation, one-time join password
                                   └─ OpenTofu (terraform/guest): clone the golden image
                                                          │
                     first boot: lab-firstboot fetches the join password ("joining"),
                     ansible-pull joins AD and applies the role, then reports ("ready")
          ◄── progress (the page polls; the worker reads nginx's lab-events log)
          ◄── "Connect": Apache Guacamole opens SSH to the machine, already logged in
```

## The page

Modelled on Microsoft Dev Box's developer portal: **New workstation** opens one form
(username, checked as you type; role from `catalog/`), the dialog closes on **Create**,
and a tile shows the machine's status, the current step and a progress bar. When it's
ready, **Connect** opens a terminal in a new tab; the **⋯** menu has details (address,
username, password), a link for another device, and **Delete**.

There are no accounts. Each machine has a random secret token; the browser keeps it in
`localStorage` and sends it in a header (`X-Lab-Token`), never in a URL, so it never
appears in a log. Only a hash of it is stored. "Copy link for another device" puts it
after a `#`, which browsers don't send to servers.

## Decisions

**Operations run in their own units.** The worker only dispatches: it turns a request
into an operation record and starts `lab op run <id>` with `systemd-run`. Restarting
the worker (every deployment does) never kills a build, and each operation's output is
in its own log and journal unit. If a unit dies without finishing, the worker marks the
operation failed.

**Addresses come from the VM ID.** Guests get the first free VM ID in the guest range
(131–139); its IP and MAC follow (VM 1NN → 10.10.10.NN, BC:24:11:00:00:NN). The portal
accepts at most four guests at a time (`max_guests`, pve01's memory).

**Two processes, two privilege levels.** The web side (`portal.py`, user `labportal`,
sandboxed by systemd) can only reserve a username and drop a request file; it reads
everything else. The worker and `lab` (root) hold the Proxmox token and the runner key.
A username is reserved by creating its password file with `O_EXCL`, so two requests
can't take the same name, and the worker also refuses names that exist in AD.

**The visitor gets an AD account**, in `OU=Guests`, with RFC2307 attributes and the
password the portal generated (stored only on mgmt01). It's deliberately in no role
group (that would admit them to every machine of the role). Their machine's computer
account has them as `managedBy`; the machine reads that from AD (`roles/ad_join`) and
admits only its owner and `ws-admins`.

**Terminal: Apache Guacamole 1.6** (Docker on mgmt01), with JSON authentication only: no
database and no Guacamole accounts. For each **Connect**, the portal builds a login for
one SSH connection to the visitor's own machine, valid for 60 seconds: HMAC-SHA256
signed, then AES-128-CBC encrypted with a key shared only with Guacamole. Before opening
it, the page signs out any Guacamole session the browser still has, because Guacamole
would otherwise reuse that session and ignore the new login. Workstations accept SSH
passwords only from mgmt01's address, where Guacamole runs; everything else is key-only.

## Progress

The worker doesn't poll machines; it reads what the lab already produces:

| Step | Signal |
|---|---|
| Request received | the request file |
| Identity ready | `lab` finished ansible/identity.yml for this host |
| VM created | OpenTofu's `Creation complete` line |
| Joining the domain | the machine fetched its one-time join password (nginx lab-events log, by IP) |
| Ready | the first configuration run finished and requested `/lab-events/configured` |

The lab-events log is written only by those two nginx locations, as JSON
(`roles/lab_web`); the worker remembers its position, so a restart doesn't miss a step.

**Failures are reported, not waited out.** If the join-password request is refused,
the build fails at once with that reason. A build with no new step for 20 minutes
fails as stalled. `lab reimage ws-<user>` rebuilds a failed one.

## Admin page and removal

`/admin` lists every workstation in any state: the fleet (with what Proxmox reports)
and the guests, each with its last configuration run. The lab's own machines (pve01,
dc01, mgmt01) aren't workstations and aren't listed; the web side and the worker also
refuse them by name, and nothing that deletes knows about anything outside the
workstation inventory. Sign-in is a lab admin's own AD account: the portal binds to
dc01 over LDAPS and admits members of `ws-admins`, nested groups included. The password
is never stored; a signed, HttpOnly, SameSite=Strict cookie carries the session for 8
hours. Sign-in attempts are rate-limited by nginx, and admin actions need a header only
the page's own code sends.

An admin ticks machines and presses **Delete** under the table; a warning lists every
one and says it can't be undone. Then each row shows its steps:

- **guest:** `lab guest delete` destroys the VM (OpenTofu), then ansible/identity.yml
  removes the computer account, the owner's account, the DHCP reservation and lease
  (releasing the lease makes the DHCP hook delete the DNS records at once) and the join
  password, then the record, the password and the state file.
- **fleet:** the worker commits the removal of `inventory/workstations/<host>.yml` to
  `main` ("Remove ws03 (admin jrhodes, from the admin page)") and approves the destroy.
  CI checks the commit and moves `stable`; the reconciler destroys the VM and cleans up
  the same way. That takes a few minutes, shown as "Waiting for the checks".

If a fleet machine disappears from the inventory any other way (a commit), the
reconciler doesn't destroy it until an admin presses **Approve** on this page.

The **Activity** list shows every operation: builds, deletes, image builds, reconciles,
who started them and how they ended.

## Exposure

`lab.radicallydecent.com` is the portal and `/guacamole/`; `pve.radicallydecent.com` is
the Proxmox UI. Both sit behind the VPS's sign-in gate (one 12-hour session for both),
and both hops behind it are TLS with verified certificates. The tunnel's firewall on
pve01 admits only the Proxmox UI and the portal relay. mgmt01's internet-facing port
(8443) serves the portal and the terminal only; install records, join passwords and the
events endpoint exist only on its lab-facing port (443). See [vps/](../vps/README.md).
