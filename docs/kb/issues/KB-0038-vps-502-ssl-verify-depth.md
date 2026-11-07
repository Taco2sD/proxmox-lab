---
id: KB-0038
title: "The VPS answered 502 after turning on upstream certificate checks"
status: fixed
found_by: build
signal: "HTTP 502 from the VPS"
found: 2026-11-06
resolved: 2026-11-06
severity: high
hosts: [vps]
components: [nginx, sign-in-gate]
patterns: [default-doesnt-fit]
commits: [de27580]
related: []
---

# KB-0038: The VPS answered 502 after turning on upstream certificate checks

## Symptom

With `proxy_ssl_verify on` for the hop to the lab, every request to lab. and pve. returned 502.

## How it was found

Right after enabling verification on the VPS.

## Root cause

nginx's `proxy_ssl_verify_depth` defaults to 1, too short to verify a Let's Encrypt chain (leaf, intermediate, root).

## Fix

`proxy_ssl_verify_depth 2` (de27580, `vps/nginx-lab.radicallydecent.com`).

## Verification

Both sites answered with verified TLS end to end.

## Prevention

vps/README.md records the edge's settings; the monitoring's public sign-in probe checks the VPS path.
