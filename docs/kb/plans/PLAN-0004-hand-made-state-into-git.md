---
plan: PLAN-0004
title: Bring hand-made infrastructure state and secret rotation into git
status: proposed
owner: unassigned
created: 2026-11-07
issues: [KB-0105, KB-0108, KB-0010]
patterns: [hand-made-state]
components: [opentofu, proxmox-ve, mgmt01, dc01, acme-certs, windows-host, lab-cli]
---
## Goal

A rebuild from git produces dc01's and mgmt01's VM and container definitions as they are
today, drift shows up in `lab doctor`, and every secret has a written rotation procedure.

## Why

CT 106's features and disk size, VM 105's sizing, Proxmox's ACME setup, `cluster.fw` and
the Hyper-V VM's settings were all made by hand and exist only on the hosts (KB-0105).
Secrets never expire and have never been rotated (KB-0108).

## Steps

- [ ] `terraform/infra`: adopt VM 105 and CT 106 with `import` blocks, iterate until
      `tofu plan` is empty, and run it from `lab` like the fleet (state on mgmt01).
- [ ] Record pve01-level settings in a pve01 role or group_vars: the ACME account and plugin
      (`pvenode config set --acme ...`), and the `cluster.fw` options.
- [ ] host-setup/02-create-pve-vm.ps1: today's memory (32 GB), vCPU (12), and the stop and
      start actions, so the script matches the running VM.
- [ ] docs/operations.md "Rebuilding mgmt01 from nothing": today's sizes (14 GB root, 3 GB,
      2 cores), until the infra root makes them automatic.
- [ ] The Secrets table gets a "Rotating" column. Rotate session-key once end to end as
      the test.
- [ ] Proxmox API tokens get `--expire` one year out, with a `lab doctor` warning 30 days
      before.

## Risks and rollback

- Importing live guests into OpenTofu is safe while `plan` shows no changes. Never apply a
  plan that replaces 105 or 106. Rollback is `tofu state rm`, and the guests stay as they
  are.
- Rotating session-key signs everyone out of the admin page. Do it outside demo times.

## Done when

`tofu plan` for the infra root is empty, `lab doctor` reports a deliberately changed setting
as drift, and every secret in docs/operations.md has a rotation line.
