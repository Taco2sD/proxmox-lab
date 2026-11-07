---
id: KB-0040
title: "Admin sign-in failed over LDAPS: 'Missing Authority Key Identifier'"
status: fixed
found_by: build
signal: "LDAPS TLS error in the portal"
found: 2026-11-06
resolved: 2026-11-06
severity: high
hosts: [dc01, mgmt01]
components: [ldaps, portal, acme-certs]
patterns: [upstream-default-changed]
commits: [79bc5a1]
related: []
---

# KB-0040: Admin sign-in failed over LDAPS: "Missing Authority Key Identifier"

## Symptom

The admin page's AD sign-in failed with a TLS verification error naming a missing Authority Key Identifier.

## How it was found

First test of the admin sign-in.

## Root cause

Python 3.13+ verifies certificates strictly (VERIFY_X509_STRICT), and the self-signed certificate Samba generates for LDAPS lacks that extension.

## Fix

A Let's Encrypt certificate for dc01.lab.radicallydecent.com via acme-dns, verified against the system trust store (79bc5a1, `ansible/roles/samba_ldaps`).

## Verification

Sign-ins over LDAPS succeeded with certificate verification on.

## Prevention

The LDAPS probe in the monitoring reports this certificate's expiry (CertificateExpiresSoon).
