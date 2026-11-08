---
id: KB-0161
title: Prometheus and blackbox stayed down after mgmt01 rebooted
status: fixed
found_by: investigation
signal: Containers exited after `pct reboot 106` (KB-0155's restarts)
found: 2026-11-08
resolved: 2026-11-08
severity: high
hosts: [mgmt01]
components: [prometheus, blackbox, docker]
patterns: [upstream-default-changed]
commits: []
related: [KB-0155, KB-0008]
---
## Symptom

After mgmt01's container was rebooted (KB-0155), Grafana, pve-exporter and Guacamole came
back but Prometheus and blackbox stayed exited, although all of them have
`restart: unless-stopped`. Monitoring was half down until someone ran
`docker compose up -d` by hand.

## How it was found

Checking the lab after the restarts. dockerd's shutdown log named the difference:

```
ShouldRestart failed ... container=8524ebcc... (prometheus) hasBeenManuallyStopped=true
ShouldRestart failed ... container=38d21bf4... (blackbox)   hasBeenManuallyStopped=true
ShouldRestart failed ... container=ca1ed40c... (grafana)    hasBeenManuallyStopped=false
```

## Root cause

The role reloaded both on a config change with `docker compose kill -s SIGHUP`. Docker
records any `kill` through its API as the container having been stopped by hand
(`HasBeenManuallyStopped` in its config.v2.json), even for a signal that doesn't stop it.
`unless-stopped` then means "don't start this one" at the next daemon start. Reproduced:

```
prometheus False      # before
docker kill -s HUP lab-monitoring-prometheus-1
prometheus True       # after; the process is still running
```

Grafana is restarted instead of signalled, so it never got the mark.

## Fix

The handlers send the signal from inside the container,
`docker compose exec -T <service> kill -HUP 1`: same reload, and Docker's API never sees a
kill (ansible/roles/monitoring/handlers/main.yml). Verified: both reload ("Reloaded config
file", "Completed loading of configuration file") and the mark stays `False`.
Prometheus's mark from the test was cleared by restarting it once.

## Verification

After the fix, `HasBeenManuallyStopped` is False for every monitoring container.

## Prevention

Reloads go through `docker exec`; the handlers' comment says why. Any future container
reload by signal should do the same.
