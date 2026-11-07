---
id: KB-0050
title: "Reconciler deploy failed: `file` used as a Jinja filter (it's a lookup)"
status: fixed
found_by: build
signal: "Reconcile operation failed (ansible/site.yml)"
found: 2026-11-07
resolved: 2026-11-07
severity: medium
hosts: [mgmt01]
components: [pxe-image-factory, reconciler, ci]
patterns: [ci-blind-spot, ansible-parsing-gotcha]
commits: [0e191de]
related: [KB-0006, KB-0049]
---

# KB-0050: Reconciler deploy failed: `file` used as a Jinja filter (it's a lookup)

## Symptom

Operation 20261107-134546-reconcile-a43f failed: `No filter named 'ansible.builtin.file'` while setting pxe_desktop_role_packages.

## How it was found

The reconciler's run failed after CI passed.

## Root cause

The pxe role read the catalogue with `map('ansible.builtin.file')`; `file` is a lookup plugin, not a filter, and Jinja only resolves filters when the expression is evaluated, which ansible-lint doesn't do.

## Fix

Read the catalogue with a lookup loop (0e191de, `ansible/roles/pxe/tasks/main.yml`).

## Verification

The next reconcile deployed cleanly.

## Prevention

Counted by the first OperationsFailing alert (KB-0006).
