---
id: KB-0009
title: The Lab overview's alert table showed only the first firing alert
status: fixed
found_by: build
signal: Lab overview screenshot - Firing alerts stat said 3, the table listed 1
found: 2026-11-07
resolved: 2026-11-07
severity: low
hosts: [mgmt01]
components: [grafana]
patterns: [dashboard-query-shape]
commits: [3d34679]
related: [KB-0012]
---
## Symptom

The "Firing alerts" stat showed 3; the "Firing alerts" table beside it listed one row.

## How it was found

While building the monitoring, from a rendered screenshot of the dashboard (headless Edge against
mgmt01), compared with `ALERTS{alertstate="firing"}` in Prometheus.

## Root cause

Prometheus's instant query in table format returns one data frame per series. A Grafana table panel
shows only the first frame unless the frames are combined, so every alert after the first was hidden.

## Fix

A `merge` transformation first in the alert table and in the Machine dashboard's two tables (failed
units, pending updates), before the filter and rename transformations.

## Verification

The next screenshot listed every firing alert (hundreds, during the alert storm of
[KB-0007](KB-0007-per-unit-failed-alert-storm.md)), matching the stat.

## Prevention

Tables over Prometheus series always start with `merge`; dashboards are checked by rendering them,
not only by running their queries.
