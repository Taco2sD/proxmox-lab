---
id: KB-0039
title: "Admin sign-in made the browser ask for the demo password again"
status: fixed
found_by: build
signal: "Browser Basic-auth prompt after a failed admin sign-in"
found: 2026-11-06
resolved: 2026-11-06
severity: medium
hosts: [vps, mgmt01]
components: [portal, sign-in-gate]
patterns: [browser-session-state]
commits: [42c6ac7, 338cdbe]
related: [KB-0037]
---

# KB-0039: Admin sign-in made the browser ask for the demo password again

## Symptom

A wrong admin password on /admin made the browser forget the lab access credentials and prompt for them again.

## How it was found

Testing the admin sign-in behind the VPS's Basic auth.

## Root cause

Behind HTTP Basic auth, any 401 from the application makes browsers discard the cached Basic credentials.

## Fix

The app answers 403, never 401 (42c6ac7). Basic auth was later replaced by the oauth2-proxy sign-in gate (338cdbe).

## Verification

Failed admin sign-ins showed the page's own error and kept the lab session.

## Prevention

Applications behind an auth proxy keep 401 for the proxy.
