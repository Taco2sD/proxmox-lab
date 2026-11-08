---
id: KB-0156
title: Ubuntu's needrestart would restart services by itself after every unattended update
status: fixed
found_by: investigation
signal: needrestart source (/usr/sbin/needrestart, Ubuntu mode) read while adding restart metrics
found: 2026-11-07
resolved: 2026-11-08
severity: high
hosts: [dc01, mgmt01, workstations]
components: [patching, samba-ad, dhcp, docker]
patterns: [default-doesnt-fit, upstream-default-changed]
commits: [b09efe3, 00fe16c]
related: [KB-0005, KB-0155]
---
## Symptom

None yet: caught before it fired. dc01 and every workstation already had needrestart
(Ubuntu installs it), and roles/patching ([KB-0005](KB-0005-no-automatic-security-updates.md))
had just turned on daily unattended security updates. The next update of a library
samba or dnsmasq uses would have restarted them, unannounced, around 06:00.

## How it was found

While adding restart metrics ([KB-0155](KB-0155-patched-but-not-restarted.md)): checking
needrestart's configuration on dc01 showed no restart mode set
(`#$nrconf{restart} = 'i';`, commented out), and its apt hook calls
`apt-pinvoke -m u`. Ubuntu's `ubuntu-mode.patch` (changelog: "By default we want
needrestart to be quieter, restart services that need it") makes that mode restart
automatically:

```
/usr/sbin/needrestart:
    if ($opt_m eq 'u') {
        if(defined $nrconf{restart}) { ... }      # explicit mode wins
        ...
        } else {
            $nrconf{restart} = 'a';               # automatic restarts
```

## Root cause

A distribution default that suits a single-purpose cloud server (restart what an update
touched, right away) doesn't fit a lab with one domain controller, one container host
carrying the portal, and people's desktops. It applies to every apt run through the hook,
unattended ones included.

## Fix

roles/patching writes `/etc/needrestart/conf.d/50-lab.conf` with
`$nrconf{restart} = 'l';` (list only; an explicit mode also turns off Ubuntu mode), plus
`kernelhints = -1` and `ucodehints = 0` (report, never a dialog). It is the role's first
task, and `patching` is now the first role in every play of `ansible/site.yml` and in
`ansible/local.yml`, so no apt run on a server or a new workstation happens before the
setting is in place.

## Verification

On dc01, mgmt01, pve01, ws35 and ws36 the file is in place and
`needrestart -b -r l` lists without restarting. dc01's unattended run at 06:00 on
2026-11-08 and the workstations' (06:21 and 06:32) installed nothing that needed a
restart, and their journals show no needrestart restarts:
`journalctl --since -4h | grep -i needrestart` on dc01, mgmt01 and pve01 shows nothing
but the check itself.

## Prevention

What needs a restart is now reported instead (ServicesNeedRestart). The
[default-doesnt-fit](../patterns/default-doesnt-fit.md) pattern: when a role turns on
automation (here unattended upgrades), check what else the distribution hooks onto it.
