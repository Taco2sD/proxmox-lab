---
id: KB-0108
title: Every lab secret is long-lived, and none has a written rotation procedure
status: open
found_by: review
signal: "pre-mortem: pveum user token list (expire 0); docs/operations.md Secrets table"
found: 2026-11-07
severity: low
hosts: [pve01, mgmt01]
components: [opentofu, portal, guacamole, console-relay, pve-exporter, lab-cli]
patterns: [hand-made-state]
commits: []
related: [KB-0102]
---
## Symptom

The secrets that hold the lab together were each made once and never expire:

```
$ pveum user token list terraform@pve
 tofu │ OpenTofu on RAREEARTH-PC │ 0 │ 0      # expire 0 (never), privsep 0 (the user's full rights)
$ ls -la --time-style=+%F /etc/lab-portal/ /root/.ssh/     # on mgmt01, abridged
  session-key, json-secret-key (Guacamole), console-secret 2026-11-06/07; github_deploy 2026-11-06
```

docs/operations.md's **Secrets** table says where each one lives, but not how to replace
it, what breaks while it's being replaced, or who needs the new value.

## How it was found

The pre-mortem's "secrets without rotation" check.

## Root cause

Secrets were created by roles (made once, if missing) or by hand during the build.
Nothing gives them an expiry, and nobody has rotated one yet, so the procedure has never
been exercised.

## Fix

Proposed in PLAN-0004, not applied:

1. A "Rotating" column in docs/operations.md's Secrets table. For most role-made secrets
   the procedure is: delete the file and run `lab deploy` (the role makes a new one).
   Write down the side effects (session-key: everyone signed out; json-secret-key: open
   Guacamole sessions end; console-secret: none).
2. Give the Proxmox API tokens an expiry (`--expire`) one year out, and add a
   `lab doctor` check that warns 30 days before.
3. The deferred SSH-certificate idea (short-lived certs from a CA on mgmt01) removes the
   stored guest passwords entirely. It's already on the user's list of deferred ideas.

## Verification

Not fixed yet. Done when each secret has a written rotation step, and one rotation
(session-key) has been done end to end.

## Prevention

A secret is finished only when its rotation is written down and has been tried once.
