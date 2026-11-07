---
id: KB-0023
title: "Desktop golden image build hung: the RAM-backed installer ran out of memory"
status: fixed
found_by: build
signal: "Image build stalled; operation stopped by hand"
found: 2026-11-07
resolved: 2026-11-07
severity: medium
hosts: [pve01, mgmt01]
components: [golden-image, pxe-image-factory, desktop, lab-cli]
patterns: [ram-backed-installer-limits]
commits: [83a74e1]
related: [KB-0021, KB-0006]
---

# KB-0023: Desktop golden image build hung: the RAM-backed installer ran out of memory

## Symptom

`lab image build desktop` stopped making progress during the install of the Ubuntu Desktop packages. The operation (20261107-142719-image-build-89be) was stopped by hand.

## How it was found

Watching the builder VM's console during the first desktop image build.

## Root cause

The desktop packages were installed by the autoinstall inside the live installer, whose root filesystem and ISO copy sit in RAM. The extra few GB of packages exhausted it.

## Fix

The installer installs only the base system; the builder installs the desktop and every desktop role's packages at its own first boot, from its disk (`ansible/roles/pxe/templates/image-user-data.yaml.j2`). The builder VM got 8 GB.

## Verification

The next `lab image build desktop` produced template 9003; desktop clones are ready in about 50 seconds.

## Prevention

Keep the installer stage minimal; do heavy work after the first boot. The stopped build was one of the failures the first OperationsFailing alert counted (KB-0006).
