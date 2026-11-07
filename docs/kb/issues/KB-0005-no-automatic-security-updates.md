---
id: KB-0005
title: mgmt01 and pve01 had no automatic security updates; 76 were waiting on mgmt01
status: fixed
found_by: monitoring
signal: SecurityUpdatesPending
found: 2026-11-07
resolved: 2026-11-07
severity: high
hosts: [mgmt01, pve01, dc01, workstations]
components: [patching, mgmt01, pve01]
patterns: [missing-baseline]
commits: []
related: []
---
## Symptom

The Lab overview's "Security fixes" stat showed 76 the first time it rendered, and the
Pending updates panel put mgmt01 at 113 packages behind. All 76 security updates were on
mgmt01, the machine that runs the portal, Guacamole, the runner and the monitoring. They
included libc6, apt, gpgv, ca-certificates and the krb5 libraries.

## How it was found

node_exporter's apt collector (`apt_upgrades_pending`, which ships with Ubuntu's
`prometheus-node-exporter` package) fed both the dashboard stat and the
SecurityUpdatesPending rule, which was pending on mgmt01:

```
sum by (host) (apt_upgrades_pending{origin=~".*-security.*"})
  {host="mgmt01"} 76
```

## Root cause

There was no patching baseline, so each machine had whatever its install happened to
bring:

| Machine | unattended-upgrades | Why |
|---|---|---|
| dc01 | installed, Ubuntu's defaults (release and security origins) | full Ubuntu server install |
| workstations | installed, Ubuntu's defaults | both golden images are Ubuntu server installs |
| mgmt01 | **not installed** | LXC built from the minimal Ubuntu container template, which leaves it out |
| pve01 | **not installed** | Proxmox VE's installer doesn't install it |

Nothing in the repository said what any machine should do about updates, so nothing
noticed the two that did nothing.

## Fix

A new role, `ansible/roles/patching`, applied to every machine: dc01, pve01 and mgmt01 in
`ansible/site.yml`, and the workstations in `ansible/local.yml`. `unattended-upgrades`
is also added to `image_packages` (`ansible/group_vars/all.yml`), so future images have
it from the first boot.

- **Security origins only.** `/etc/apt/apt.conf.d/52lab-unattended-upgrades` uses
  `#clear` to empty the origin lists from the package's own `50unattended-upgrades`, then
  allows only `origin=Ubuntu,archive=<codename>-security` on Ubuntu and
  `origin=Debian,codename=<codename>-security,label=Debian-Security` on pve01. On dc01 and
  the workstations, this also takes away the release-pocket origin Ubuntu's defaults had
  enabled.
- **Never Proxmox's repository.** A Proxmox VE upgrade (kernel, QEMU, pve-manager) is a
  planned `apt full-upgrade` with a reboot of every VM behind it.
- **No automatic reboots.** The RebootRequired alert and the dashboards report a pending
  reboot, and a person picks the time.
- **Fresh lists daily** (`20auto-upgrades`), run by Ubuntu's and Debian's own
  `apt-daily*.timer`s. The role's apt task waits up to 10 minutes for the dpkg lock
  rather than failing when a scheduled run holds it.
- No global `Dpkg::Options`. They would also change how every manual upgrade treats
  config files.

Then mgmt01 was brought current by hand, with exactly what the role does followed by
`unattended-upgrade -v`. Patched code only takes effect once the processes using it are
restarted, and the container has no needrestart. So after waiting for a reconcile run in
progress to finish, these were restarted: `systemctl daemon-reexec`, nginx, lab-portal,
lab-portal-worker, prometheus-node-exporter, tftpd-hpa, journald, logind, networkd,
resolved, networkd-dispatcher, cron and the gettys.

## Verification

- The patching role, run on its own against the three servers: changed on the first run,
  `changed=0` on the second.
- Effective settings (`apt-config dump Unattended-Upgrade`): only the security pattern on
  each machine, and `Automatic-Reboot "false"`.
- pve01: `unattended-upgrade --dry-run -v` shows
  `Allowed origins are: origin=Debian,codename=trixie-security,label=Debian-Security`,
  and nothing from Proxmox.
- mgmt01: `All upgrades installed`. Pending security updates went from 76 to 0, and
  `node_reboot_required 0`.
- Portal, Guacamole and Grafana all return 200 through nginx. `lab status` works, all
  monitoring containers are up, and no units have failed.
- Prometheus: `sum by (host) (apt_upgrades_pending{origin=~".*-security.*"})` is empty
  for every host, and SecurityUpdatesPending is `inactive`.
- The three `tar: Exiting with failure status` lines in the run's log are harmless.
  unattended-upgrades reads each package's config file list to look for prompts, and
  postfix lists obsolete files marked `remove-on-upgrade` that aren't in its archive.

## Prevention

- The role makes patching part of every machine's definition, including machines added
  later and anything built from the images.
- SecurityUpdatesPending fires when a machine has had security updates waiting for 24
  hours. That catches a machine where the timers stopped, the lists can't be fetched or
  a package is held back.

Still open (for review, not covered by this fix):
- **Restarts after patching.** Processes keep the old libraries until they restart.
  mgmt01 still runs dockerd, containerd, docker-proxy and dbus on pre-patch libraries,
  because restarting dockerd restarts every container (Guacamole sessions drop), so it
  belongs in a quiet moment. A follow-up could install `needrestart` in list mode and
  publish "processes on deleted libraries" per host as a metric, alerting when it lasts
  more than a day.
- **First boot of a clone.** The images keep the `apt-daily-upgrade.timer` stamp from
  build time, and the timer is `Persistent=true`. So a clone first booted a day or more
  after its image was built may start unattended-upgrade straight away, alongside
  `lab-firstboot`'s ansible-pull. Ansible's apt tasks elsewhere wait only 60 s for the
  lock, and `lab-firstboot` exits on the first error. This is unconfirmed: whether
  systemd's catch-up run also waits for `RandomizedDelaySec` hasn't been checked. A
  possible fix is for `lab-generalize` to remove the apt timer stamps, or to give the
  workstations' apt tasks a longer `lock_timeout`.
