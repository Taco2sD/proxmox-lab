# Knowledge base

Every problem this lab has had, why it happened, how it was fixed and what now stops it coming
back, written so the next person can recognise the next one at a glance.

| Start here | For |
|---|---|
| [INDEX.md](INDEX.md) | Tallies, open problems, where bugs cluster, the component map |
| [issues/](issues/) | One page per problem: `KB-NNNN-<slug>.md` |
| [patterns/](patterns/) | Recurring kinds of failure, with how to spot, fix and prevent them |
| [runbooks/](runbooks/) | One page per alert rule: what to do when it fires |
| [plans/](plans/) | Action plans: clusters of problems turned into work |
| [components.yml](components.yml) | The map: every component, where it runs, what deploys it, what it needs |
| [kb.json](kb.json) | All of the above as one JSON document (generated) |

`python3 tools/kb.py build` regenerates INDEX.md, kb.json and the generated blocks;
`python3 tools/kb.py check` validates everything and runs in CI (tools/check, group `kb`).

## How a problem moves through it

1. **Detect.** An alert fires, a dashboard looks wrong, a build breaks, someone reports something,
   or a review spots a risk.
2. **Issue page.** One page per problem, written while fixing it: symptom, how it was found, root
   cause, fix, verification (with the output that proved it), prevention.
3. **Fix**, committed separately, its hash in the page's `commits`.
4. **Pattern.** Link the kind of failure it was. If it's new, write the pattern page: the next
   occurrence is recognised from the pattern, not rediscovered.
5. **Prevention.** Change what lets it recur (a convention, a check, an alert) and say so in the
   issue's Prevention section. A new alert gets a runbook.
6. **Plan.** When patterns cluster (INDEX.md: "Where bugs cluster"), or a review finds risks, a plan
   page turns them into ordered steps.

## How problems were found (`found_by`)

The difference matters: it shows what the monitoring catches and what still depends on luck.

| Value | Meaning |
|---|---|
| `monitoring` | An alert or dashboard of the monitoring stack surfaced it (docs/monitoring.md) |
| `build` | Hit while building or changing something |
| `investigation` | Noticed incidentally while investigating something else |
| `user` | A person reported it |
| `ci` | The checks (tools/check) caught it |
| `review` | Anticipated by a deliberate review before it caused harm |

`signal` says exactly what surfaced it: an alert rule's name (the runbook then lists the issue
automatically), a panel, a command's output, a quote from a report.

## Page templates

Front matter is YAML between `---` lines; tools/kb.py checks every key and reference. Lists can be
empty (`[]`), never left out. Component and host ids come from components.yml.

### Issue: `issues/KB-NNNN-<slug>.md`

```markdown
---
id: KB-0042
title: The problem, not the fix
status: fixed            # fixed | mitigated | open | accepted (known, deliberately not fixed)
found_by: monitoring     # see the table above
signal: SystemdUnitsFailed
found: 2026-11-07
resolved: 2026-11-07     # only when fixed or mitigated
severity: medium         # low | medium | high | critical: impact if left alone
hosts: [pve01]
components: [console-relay]
patterns: [per-connection-unit-pileup]
commits: [3d34679]
related: [KB-0013]
---
## Symptom
## How it was found
## Root cause
## Fix
## Verification
## Prevention
```

### Pattern: `patterns/<slug>.md`

```markdown
---
pattern: per-connection-unit-pileup
title: Per-connection units pile up as failed
components: [console-relay]
---
# Title
## What happens
## How to spot it        (signals, PromQL, commands)
## How to fix
## How to prevent
<!-- kb:generated:start -->
<!-- kb:generated:end -->
```

### Runbook: `runbooks/<AlertName>.md`

The file name is the alert's name; the alert carries
`runbook_url: https://github.com/Taco2sD/proxmox-lab/blob/main/docs/kb/runbooks/<AlertName>.md`.

```markdown
---
alert: TargetDown
severity: critical       # critical | warning | info, as in the rule's labels
components: [node-exporter]
---
# TargetDown
## What it means
## First five minutes
## Common causes
## Escalate / fix
<!-- kb:generated:start -->
<!-- kb:generated:end -->
```

### Plan: `plans/PLAN-NNNN-<slug>.md`

```markdown
---
plan: PLAN-0001
title: ...
status: proposed         # proposed | in-progress | done
created: 2026-11-07
issues: [KB-0001]
patterns: [missing-baseline]
components: [patching]
---
## Goal
## Why
## Steps                 (a "- [ ]" checklist, smallest safe steps first)
## Risks and rollback
## Done when
```

## Working on the lab

**Before changing anything**
1. Read [INDEX.md](INDEX.md) (or [kb.json](kb.json), the same graph as data). Find the
   components you're about to touch and read their issues: most mistakes here have been made once.
2. Facing a failure, search the patterns first (`grep -ril '<symptom words>' docs/kb/patterns`)
   and follow "How to spot it" before forming theories. If the alert has a runbook, start there.
3. Read docs/operations.md (how changes reach the lab) and docs/boundaries.md (which tool owns what).

**Changing the live lab**
- Changes go through git: commit to `main`, CI runs tools/check, `stable` moves, the reconciler
  deploys servers and workstations pull. Edit deployed files by hand only to verify a fix you're
  about to commit, and make the role do exactly the same.
- Rebooting dc01, pve01 or mgmt01, or deleting VMs, accounts or data, is a planned change, not a
  side effect of a fix.
- Pause the reconciler while testing a deploy by hand (`touch /var/lib/lab/reconcile.paused`),
  and remove the file when done.
- Verify with real output (a command, a query, a screenshot), and put that output in the issue.
- The repository is public: no secrets, no real people's names.

**Writing it down**
- One issue page per problem, with the next free id (`ls docs/kb/issues | tail`).
- Link a pattern, or write a new one if none fits.
- Name `found_by` honestly: a problem stumbled on while doing something else is
  `investigation`, not `monitoring`, even if monitoring could have caught it.
- Don't edit between `<!-- kb:generated:start -->` and `<!-- kb:generated:end -->`, nor INDEX.md
  or kb.json: run `python3 tools/kb.py build`, then `python3 tools/kb.py check`.
- A new alert rule needs its runbook page and `runbook_url` in the same commit (check enforces it).
- New component? Add it to components.yml with its roles and `depends_on`; don't rename an id.
- A pattern or component with several issues, or an open issue of high severity, is a candidate
  for a plan (plans/).
