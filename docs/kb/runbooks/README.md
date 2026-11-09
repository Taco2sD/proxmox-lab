# Runbooks

One page per Prometheus alert rule in ansible/roles/monitoring/files/alerts.yml, named after
the rule (`TargetDown.md` for `alert: TargetDown`). Every rule carries a `runbook_url`
annotation pointing at its page, so the link is right there in the alert, on Prometheus's
alerts page (https://lab.radicallydecent.com/prometheus/alerts) and on the Lab overview.
`tools/kb.py check` (part of tools/check, so CI) fails if a rule has no page, a page has
no rule, or an annotation points somewhere else.

## What a page holds

| Section | For |
|---|---|
| front matter | `alert` (the rule's name), `severity` (as in the rule), `components` (ids from ../components.yml) |
| What it means | The rule's expression and what it is really telling you, including what it deliberately ignores |
| First five minutes | Commands that work in this lab, in the order to run them: read-only first |
| Common causes | What has caused it, or plausibly will, here |
| Escalate / fix | What to change and where (the role, git), and what never to do |
| generated block | Filled by `tools/kb.py build`: every issue in ../issues/ whose `signal` is this alert |

## The loop

```
alert fires ──► runbook (what to check first)
                  │
                  ▼
           fix it, in git ──► issue page in ../issues/ (signal: <AlertName>)
                                   │
                                   ├──► the runbook lists it under "Past occurrences" (generated)
                                   └──► patterns: [...] ──► ../patterns/<slug>.md lists every issue
                                                            of that kind, across all alerts
```

1. An alert fires; its `runbook_url` opens the page here.
2. Whoever handles it fixes the cause in git (the reconciler deploys it) and writes an issue
   page in ../issues/ with `signal:` set to the alert's exact name and `found_by: monitoring`.
3. `python3 tools/kb.py build` adds that issue to this runbook's generated block, and to the
   pattern pages the issue names. The next person to get this alert sees what caused it
   before, how it was fixed and how it was verified.
4. When the same pattern shows up under several alerts, its pattern page is where the
   lasting fix (a role default, a check, a new alert) gets decided; a plan in ../plans/
   tracks the work if it is bigger than one commit.

## Writing or changing a runbook

- New alert rule: add its page in the same commit (the check enforces it), with
  `runbook_url: https://github.com/Taco2sD/proxmox-lab/blob/main/docs/kb/runbooks/<AlertName>.md`.
- Commands must run as written on the named host. Read-only steps come first; anything
  that changes state says what it affects (dc01 and pve01 restarts take other things down).
- Learned something during an incident that the page didn't say? Add it here, and record
  the incident itself as an issue page.
- Don't edit between the `kb:generated` markers: `tools/kb.py build` rewrites that part.
