# Self-service workstations

A web page where a visitor enters a username and picks a role, and the lab builds them
a workstation: AD account, VM, install, domain join, role, and a terminal session in the
browser when it's ready. Everything goes through git, the same as a hand-made change.

## Flow

```text
browser ──► lab.radicallydecent.com (VPS: password prompt, TLS)
               │ WireGuard tunnel
               ▼
         mgmt01: portal (web app) ──► request queue ──► worker
                                                         │ 1. write inventory/guests/<host>.yml
                                                         │ 2. git commit + push (deploy key)
                                                         │ 3. lab apply  (one run per batch)
                                                         ▼
                              Ansible: AD user + computer account + reservation + record
                              OpenTofu: VMs, created in parallel
                              PXE + autoinstall, first boot: ansible-pull (all in parallel)
               ◄── progress (Server-Sent Events) ── phase tracker
               ◄── terminal (Apache Guacamole, SSH) when ready
```

## Decisions

**Batching instead of one OpenTofu state per machine.** OpenTofu only holds its state
lock while it creates or destroys VMs (about 35 seconds); installs and configuration run
afterwards, outside OpenTofu, in parallel. One run also creates or destroys many VMs at
once. So the worker takes every waiting request, makes one commit and runs one
`lab apply`. Requests that arrive during a run go into the next batch.

**One file per guest machine.** Requests live in `inventory/guests/<host>.yml`, not in
`workstations.yml`. Adding or removing a machine is adding or deleting one file, so
concurrent requests never conflict in git, the history reads as one commit per batch,
and the hand-maintained file is never rewritten by a program. OpenTofu and Ansible
read `workstations.yml` plus every file in `guests/`.

**Addresses come from slots.** Guest machines use slots 1–9: VM ID 13N, IP 10.10.10.3N,
MAC BC:24:11:00:00:3N. The portal refuses new requests when the configured limit is
reached (pve01 has room for about four installs at a time).

**The visitor gets an AD account.** `<username>` is created in `OU=Guests` (role
`ad_guest_users`) with RFC2307 attributes and a generated password, which is stored only
on mgmt01 (never in git). It is deliberately not put in the role's group (artists or
programmers): that would admit them on every machine of the role. Their machine admits
only them and `ws-admins`: the
workstation reads its own `inventory/guests/<host>.yml` from its git checkout and adds the
owner to SSSD's `simple_allow_users`.

**Terminal: Apache Guacamole.** Browser-based SSH (and RDP later). The portal signs a
short-lived token with Guacamole's JSON auth extension, so the visitor's terminal opens
already logged in. Workstations allow SSH password login only from mgmt01's address,
where Guacamole runs; everything else stays key-only.

**Progress comes from signals the lab already produces:**

| Phase | Signal |
|---|---|
| Request recorded | commit pushed |
| Identity prepared | `infra.yml` and `otp.yml` finished |
| Machine created | OpenTofu `Creation complete` |
| Installing Ubuntu | installer fetched its host record (nginx log on mgmt01) |
| Install finished | one-time password fetched |
| Joining the domain | `dNSHostName` set on the computer account |
| Ready | first configuration run finished, SSH answers |

**Exposure.** `lab.radicallydecent.com` becomes the portal (and `/guacamole/`); the
Proxmox UI moves to `pve.radicallydecent.com`. Both stay behind the VPS password prompt.
The tunnel's firewall on pve01 admits the portal and Guacamole on mgmt01 and the Proxmox
UI, nothing else.

**Removal is manual for now:** delete the guest's file (or use the portal's delete
button, which does the same through git), then `lab apply` and `lab prune`.
