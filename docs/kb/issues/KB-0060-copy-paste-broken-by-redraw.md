---
id: KB-0060
title: "Copy and paste stopped working on the portal pages"
status: fixed
found_by: build
signal: "Text selection lost every few seconds"
found: 2026-11-07
resolved: 2026-11-07
severity: low
hosts: [mgmt01]
components: [portal]
patterns: []
commits: [277e9b3]
related: []
---

# KB-0060: Copy and paste stopped working on the portal pages

## Symptom

Selected text on My lab, the admin page and the welcome page lost its selection before it could be copied, and a click that ended a selection ticked an admin row.

## How it was found

Trying to copy an SSH command from My lab.

## Root cause

The pages redraw on a timer; each redraw replaced the selected nodes.

## Fix

The timed redraw waits while text is selected, and a click ending a selection doesn't toggle a row (277e9b3, `ansible/roles/portal/files/common.js` and the pages).

## Verification

Copying the SSH command works.

## Prevention

None beyond the code comment.
