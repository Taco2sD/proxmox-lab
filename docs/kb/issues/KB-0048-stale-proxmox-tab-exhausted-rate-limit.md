---
id: KB-0048
title: "Every page of lab. and pve. answered 503 because one stale browser tab used up the rate limit"
status: fixed
found_by: build
signal: "HTTP 503 from the VPS for everyone"
found: 2026-11-07
resolved: 2026-11-07
severity: high
hosts: [vps]
components: [sign-in-gate, nginx]
patterns: [client-retry-loop]
commits: [c72cbab]
related: [KB-0013]
---

# KB-0048: Every page of lab. and pve. answered 503 because one stale browser tab used up the rate limit

## Symptom

Both public sites answered 503 to every request.

## How it was found

Everyone was locked out of lab.radicallydecent.com and pve.radicallydecent.com.

## Root cause

A Proxmox tab with an expired session kept polling the API. Each poll was redirected to the sign-in page, whose rate limit counted page visits, so one tab used up the allowance shared by both sites. Changing the limit zone's key also needed a new zone name: nginx refuses that on reload, logs `[emerg]`, and keeps the old config, even though `nginx -t` passes.

## Fix

Count only sign-in POSTs, and answer 429 (c72cbab, `vps/lab-gate-limits.conf`).

## Verification

The stale tab's polling no longer affected anyone; sign-in attempts are still limited.

## Prevention

Rate limits count only what they protect. Abandoned tabs keep polling for days; KB-0013 is the same behaviour seen later in the lab's own logs.
