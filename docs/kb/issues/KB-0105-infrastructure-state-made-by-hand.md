---
id: KB-0105
title: The infrastructure servers' own definitions live only on pve01 (made by hand, not in git)
status: open
found_by: review
signal: "pre-mortem: pct config 106 / qm config 105 compared with the repo"
found: 2026-11-07
severity: medium
hosts: [pve01, dc01, mgmt01, vps, windows-host]
components: [proxmox-ve, mgmt01, dc01, opentofu, wireguard-tunnel, acme-certs, vps]
patterns: [hand-made-state]
commits: []
related: [KB-0100, KB-0010]
---
## Symptom

Git describes the workstations (OpenTofu) and the servers' configuration *inside* the
machines (Ansible), but not the machines themselves. Nothing in the repo creates or checks
these:

| State | Where it lives | In git? |
|---|---|---|
| CT 106 (mgmt01): `features: nesting=1,keyctl=1`, `rootfs size=14G` (grown by hand on 2026-11-07, KB-0010), 2 cores / 3 GB, the ISO mount point `mp0` | pve01 `pct config 106` | Comments and docs/operations.md steps only |
| VM 105 (dc01): 2 cores / 2 GB, 16 GB disk, `startup: order=1`, `onboot` | pve01 `qm config 105` | No |
| Proxmox ACME for pve.radicallydecent.com (account `default`, plugin `acmedns`) | pve01 `pvenode config` | No |
| `cluster.fw` (enabled, policy ACCEPT) | pve01 | No |
| pve01's own VM: 32 GB, 12 vCPU, `AutomaticStopAction Save` | Windows Hyper-V | host-setup/02-create-pve-vm.ps1 creates it with 12 GB; the rest was changed by hand |
| WireGuard `/etc/wireguard/lab.conf`, the VPS's nginx/oauth2-proxy | pve01, VPS | Secrets aside, partly (vps/README.md); the VPS is set up by hand |

## How it was found

```
$ pct config 106 | grep -E "features|rootfs|memory|cores"
cores: 2
features: nesting=1,keyctl=1
memory: 3072
rootfs: local-lvm:vm-106-disk-0,size=14G
$ grep -rn "size=14G" ansible terraform docs --include=*.yml --include=*.tf --include=*.md
(no match)
$ grep -n "RAM  " host-setup/02-create-pve-vm.ps1
17:$RAM        = 12GB      # static - dynamic memory is incompatible with nested virt
(Hyper-V today: MemoryStartup 34359738368, ProcessorCount 12)
```

docs/operations.md's "Rebuilding mgmt01 from nothing" starts with creating the container
by hand, and doesn't say how big it must be (8 GB, the original size, is no longer
enough).

## Root cause

The infrastructure servers predate the OpenTofu work (phases 1–2 brought only the
workstations under it), and changes since then were made with `pct`/`qm` and the Proxmox
UI. Each change was small and sensible, but none was recorded.

## Fix

Proposed in PLAN-0004, not applied:

1. A new OpenTofu root next to `terraform/fleet` (an "infra" root) that adopts VM 105 and CT 106 with `import` blocks (as was done
   for ws01–03) until `tofu plan` shows no changes. From then on, size changes are commits.
2. A `lab doctor` check (or a CI-readable export) comparing `pvenode config get`,
   `cluster.fw` and the Hyper-V VM's settings with values in group_vars, so drift is visible.
3. docs/operations.md's rebuild steps updated to today's sizes until (1) lands.

## Verification

Not fixed yet. Done when `tofu plan` for the infra root is empty, and growing mgmt01's disk
is a one-line commit.

## Prevention

Every `pct set`, `qm set`, `pvenode` or Hyper-V change gets a commit or a KB entry the same
day. See [hand-made-state](../patterns/hand-made-state.md).
