---
id: KB-0150
title: Ansible's apt tasks gave up after 60 s while unattended-upgrades held apt's locks (first boot, 06:00 runs, deploys)
status: fixed
found_by: review
signal: Review of the patching change (3388916); no failure observed yet
found: 2026-11-07
resolved: 2026-11-08
severity: medium
hosts: [workstations, dc01, mgmt01, pve01]
components: [patching, ansible-pull, reconciler, golden-image]
patterns: [lock-contention]
commits: []
related: [KB-0005]
---
## Symptom

None yet: this was anticipated, not seen. What it would look like:

- a new workstation whose first configuration run (lab-firstboot) fails with `Failed to
  lock apt for exclusive operation`, so it doesn't join AD until its next ansible-pull
  30 minutes later, by which time the portal's worker has given up on the build
  (20-minute stall);
- now and then an `ansible-pull.service` failure on a workstation between 06:00 and
  07:00 (SystemdUnitsFailed, WorkstationNotCheckingIn if it repeats);
- a reconciler deploy of `ansible/site.yml` failing on dc01, pve01 or mgmt01 at the same
  hour (ReleaseFailedToApply, OperationFailureUnresolved).

## How it was found

While the patching role (KB-0005) went in, a review asked what else takes apt's locks.
Findings on ws35 and ws36 (clones of the 2026-11-07 images):

- unattended-upgrades was **already enabled** in both golden images: Ubuntu's own
  `/etc/apt/apt.conf.d/20auto-upgrades` (`Unattended-Upgrade "1"`), installed with the
  base system. The patching role narrowed what it installs, it didn't start it.
- The images carry their builder's timer stamps: ws35's
  `/var/lib/systemd/timers/stamp-apt-daily-upgrade.timer` is 13:36, the headless image's
  build time, not the clone's first boot (18:52). Both timers are `Persistent=true`, so a
  clone first booted after a missed 06:00 catches the run up within its first hour
  (`RandomizedDelaySec=60m`), installing everything released since the image was built.
  dc01's first such run after provisioning (2026-11-05 17:47, outside the 06:00 window)
  upgraded about 120 packages in one go.
- Every apt task in the repo except the patching role's own used Ansible's default
  `lock_timeout` of 60 s: base, ad_join, node_exporter, workstation_role and desktop on the
  workstations; dhcp_server, runner, portal, guacamole and acme_cert on the servers.

No collision has happened yet: none of the 58 operation logs in `/var/log/lab/` and none
of the workstation journals contain a lock error.

## Root cause

Two schedules share apt's exclusive locks with no agreed order: unattended-upgrades
(daily, plus first-boot catch-up) and Ansible (every 30 minutes on workstations, on every
deploy on the servers, and once at enrollment). The waiting side gave up after a minute,
shorter than a normal unattended-upgrade run.

## Fix

- `ansible/site.yml` and `ansible/local.yml`: every play sets
  `module_defaults: {ansible.builtin.apt: {lock_timeout: 600}}`, so every apt task, today's
  and any added later, waits up to 10 minutes for the locks instead of 60 s. One place
  per play rather than a value on each task.
- `ansible/roles/pxe/templates/lab-firstboot.j2` (in the golden image, so from the next
  `lab image build`): enrollment stops `apt-daily.timer` and `apt-daily-upgrade.timer`
  while it runs and starts them again on exit (a shell `trap`, so also when it fails).
  Starting a `Persistent` timer evaluates missed runs again, so the new machine still
  catches up on its security updates within the hour, just after enrolling instead of
  during it. A run already in progress is left alone; the apt tasks wait for it.
  Clones of the current images get the Ansible-side wait from their first pull already.

## Verification

On ws35, a helper held `/var/lib/dpkg/lock-frontend`, `/var/lib/dpkg/lock` and
`/var/lib/apt/lists/lock` for 90 s with POSIX locks (`fcntl.lockf`, the kind apt uses),
and the same play ran an `ansible.builtin.apt` cache refresh twice:

```
== default: rc=2 after 60s
fatal: [localhost]: FAILED! => {... "msg": "Failed to lock apt for exclusive operation: Failed to lock directory /var/lib/apt/lists ...
== module_defaults: rc=0 after 88s
ok: [localhost]
```

The helper and its files were removed afterwards. The lab-firstboot change is checked
when the next image is built: on its first clone, `journalctl -b -u lab-firstboot` shows
the run, and `systemctl list-timers 'apt-daily*'` shows both timers active again.

## Prevention

The lock-contention pattern page lists what to check when adding a scheduled job. The
`lock_timeout` lives at play level, so a new role's apt tasks inherit it without anyone
remembering to add it.
