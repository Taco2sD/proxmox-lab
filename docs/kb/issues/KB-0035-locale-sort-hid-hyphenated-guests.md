---
id: KB-0035
title: "The first portal-built machine never got its one-time password"
status: fixed
found_by: build
signal: "Portal: 'An error occurred' while building ws-tester"
found: 2026-11-06
resolved: 2026-11-06
severity: high
hosts: [mgmt01]
components: [lab-cli, portal-worker]
patterns: []
commits: [f4cd70d]
related: []
---

# KB-0035: The first portal-built machine never got its one-time password

## Symptom

The first machine requested through the portal (ws-tester) stopped at "An error occurred": it never received a one-time join password.

## How it was found

First end-to-end portal build.

## Root cause

The shell version of `lab` found new machines with `comm`, comparing a list sorted by `sort` (locale order) with one sorted by Python (byte order). Hyphenated names sort differently in each, so `comm` missed ws-tester.

## Fix

`LC_ALL=C` for the sort (f4cd70d); the worker also fails builds on OTP errors and stalls instead of waiting forever. `lab` has since been rewritten in Python and works from the OpenTofu plan itself (`ansible/roles/runner/files/lab`).

## Verification

ws-tester was rebuilt and reached ready in about 10 minutes.

## Prevention

One language and one sort order per comparison; tests cover hyphenated names (`tests/test_lablib.py`).
