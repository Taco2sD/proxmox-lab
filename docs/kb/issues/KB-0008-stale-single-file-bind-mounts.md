---
id: KB-0008
title: Prometheus kept evaluating old alert rules after a deploy (single-file bind mounts)
status: fixed
found_by: build
signal: Prometheus rules API still listed the old rule after alerts.yml was redeployed
found: 2026-11-07
resolved: 2026-11-07
severity: medium
hosts: [mgmt01]
components: [prometheus, blackbox, docker, alert-rules]
patterns: [stale-single-file-bind-mount]
commits: [3d34679]
related: [KB-0007]
---
## Symptom

After the failed-units alert was rewritten (one alert per host, [KB-0007](KB-0007-per-unit-failed-alert-storm.md))
and deployed, the Lab overview still showed hundreds of per-unit `SystemdUnitFailed` alerts. The
file on mgmt01 had the new rule; Prometheus didn't.

## How it was found

While building the monitoring: the redeploy reported the rule file as changed and the reload
handler ran, yet the alert names in `ALERTS` didn't change. The rules API settled it.

## Root cause

The first compose file mounted single files (`/etc/lab-monitoring/alerts.yml:/etc/prometheus/alerts.yml`).
Docker binds a single file by inode. Ansible's copy module writes a new file and renames it over the
old one, so the path on mgmt01 named a new inode while the container kept the old one. SIGHUP made
Prometheus re-read the old content. Same for prometheus.yml and blackbox.yml.

## Fix

Configuration is mounted by directory: `/etc/lab-monitoring/prometheus:/etc/prometheus:ro` (with
`targets/` inside) and `/etc/lab-monitoring/blackbox:/etc/blackbox:ro`. The role removes the old
single-file paths. ansible/roles/monitoring/templates/compose.yml.j2 states the rule in its header.

## Verification

`docker exec lab-monitoring-prometheus-1 ls /etc/prometheus` showed alerts.yml, prometheus.yml and
targets/; `/prometheus/api/v1/rules` then listed `SystemdUnitsFailed` (one alert per host, pve01's
value 1720) instead of the old per-unit rule.

## Prevention

Mount directories, never single files, for anything Ansible deploys into a container. After a
deploy, check the running configuration through the service (rules API), not just the file.
