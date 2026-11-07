---
id: KB-0004
title: nvmf-autoconnect failed at every boot inside mgmt01's container
status: fixed
found_by: monitoring
signal: SystemdUnitsFailed
found: 2026-11-07
resolved: 2026-11-07
severity: low
hosts: [mgmt01]
components: [mgmt01]
patterns: [container-irrelevant-units]
commits: []
related: [KB-0003]
---
## Symptom

`SystemdUnitsFailed` fired for mgmt01: `nvmf-autoconnect.service` ("Connect NVMe-oF
subsystems automatically during boot") exited 1 at every boot.

## How it was found

The SystemdUnitsFailed alert on the first evening of monitoring.

## Root cause

mgmt01 is an unprivileged LXC (CT 106): it can't load kernel modules or see block devices of
its own. Ubuntu's server seed installs nvme-cli, whose `nvmf-autoconnect.service` runs
`nvme connect-all` when `/etc/nvme/config.json` or `/etc/nvme/discovery.conf` exists, and the
package ships `discovery.conf`. Without `/dev/nvme-fabrics` in a container, it fails.

The other hardware units in the container behave: smartmontools, chrony, fstrim,
systemd-pstore, the pcrlock units, nvmefc-boot-connections and node_exporter's smartmon/nvme
collectors all skip themselves (`ConditionVirtualization=!container` or a missing device).
nvmf-autoconnect is the one without such a guard. On the VMs (dc01, pve01, workstations) it
succeeds, so this only affects the container.

## Fix

`ansible/roles/runner` (mgmt01's base role) disables and masks `nvmf-autoconnect.service`,
with a comment saying why. Masked by hand the same way, then `systemctl reset-failed`.

## Verification

```
$ systemctl is-enabled nvmf-autoconnect.service
masked
$ systemctl --failed --no-legend
$                                   # empty
$ curl -s localhost:9100/metrics | grep -c nvmf-autoconnect
0
```

Prometheus: `count by (host) (node_systemd_unit_state{state="failed",host="mgmt01"} == 1)`
returns nothing, and SystemdUnitsFailed has no alert for mgmt01.

## Prevention

- The mask is in the role, so a rebuilt mgmt01 gets it.
- For any new container: run `systemctl --failed` after the first boot, and check units that
  touch hardware for a `ConditionVirtualization` guard before trusting them (see the pattern
  page).
