---
id: KB-0012
title: Dashboard titles were cut off and a no-data text filled empty table cells
status: fixed
found_by: build
signal: Lab overview screenshot - "Next c...", "Securi..." titles; "All clear" in the Unit column
found: 2026-11-07
resolved: 2026-11-07
severity: low
hosts: [mgmt01]
components: [grafana]
patterns: [dashboard-query-shape]
commits: [3d34679]
related: [KB-0009]
---
## Symptom

On the Lab overview, narrow stat panels showed "Workstation mem...", "Next c..." and "Securi...".
Later, the alert table printed "All clear: nothing is firing" in the Unit column of alerts that
have no unit.

## How it was found

While building the monitoring, from rendered screenshots of the dashboard.

## Root cause

Two-column-wide panels can't fit those titles next to the info icon. `noValue` in Grafana applies
to every empty cell of a table, not only to an empty panel.

## Fix

In the dashboard generator: even three-column widths for the top row and shorter titles (Memory
budget, Certificates, Security fixes); `noValue` removed from the alert table.

## Verification

The next screenshot showed full titles and empty Unit cells for alerts without a unit.

## Prevention

Dashboards are looked at as rendered screenshots before they're pushed; `noValue` is used only
where an empty panel is the meaning.
