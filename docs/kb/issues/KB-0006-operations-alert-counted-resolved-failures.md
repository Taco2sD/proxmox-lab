---
id: KB-0006
title: The failed-operations alert kept firing for failures that had already been put right
status: fixed
found_by: monitoring
signal: OperationsFailing
found: 2026-11-07
resolved: 2026-11-07
severity: low
hosts: [mgmt01]
components: [alert-rules, lab-metrics, lab-cli]
patterns: [alert-on-history-not-state]
commits: [3fce451]
related: [KB-0007]
---
## Symptom

On the monitoring's first evening, `OperationsFailing` ("3 lab operations failed in the
last day") was firing on the Lab overview, while nothing in the lab was broken.

## How it was found

The alert itself, on the first look at the Lab overview after the monitoring went live.
Following it up, all three failures were from that morning's development work:

```
20261107-121546-reconcile-8131    reconcile    failed  ansible/site.yml failed
20261107-134546-reconcile-a43f    reconcile    failed  ansible/site.yml failed
20261107-142719-image-build-89be  image-build  failed  stopped by hand: the installer ran out of memory
```

Each had been followed by a successful operation of the same kind (26 reconciles done
since, and a desktop image build that worked at 14:49).

## Root cause

The rule counted a stock, failures in a 24-hour window
(`lab_operations_failed_24h > 2`), instead of a state someone has to act on. A failure
that was fixed ten minutes later kept the alert up for a day, and three unrelated small
failures looked like one problem. An alert that fires when nothing needs doing teaches
people to ignore it.

## Fix

- `lab-metrics` works out, per **subject**, whether the latest finished operation failed:
  the release (reconcile), each image kind (`params.kinds`; older builds without it built
  the headless image), and each machine an operation touched. A later success on the same
  subject resolves the failure, whatever the operation was (a successful delete resolves
  a failed build of the same machine: nothing is left to fix). Per subject, not per kind,
  so a build that worked for ws38 doesn't hide one that failed for ws37.
- New metrics: `lab_operation_unresolved_failure_timestamp_seconds{kind,subject,op}`
  (present only while unresolved) and `lab_operations_unresolved`.
- The rule became `OperationFailureUnresolved` (`... > 0`), naming the operation and its
  log in the description. `lab_operations_24h` stays on the dashboard for the trend; the
  Operations stat now shows "unresolved" next to done and failed.
- An operation **stopped by hand** is recorded as failed and counts as failed: whatever
  it was doing didn't get done, so it stays unresolved until that subject next succeeds.

## Verification

Synthetic history (lab-metrics' `unresolved_failures` run on hand-made records): a failed
reconcile followed by a done one resolves; a failed desktop image build is not resolved
by a headless one; a failed build of ws37 is not resolved by a successful one of ws38; a
running operation is ignored. On mgmt01 with the real 58 operations:

```
lab_operations_24h{state="failed"} 3
lab_operations_unresolved 0
```

`promtool check rules`: 20 rules; `/prometheus/api/v1/rules`: OperationFailureUnresolved
inactive, health ok.

## Prevention

The rule of thumb is written into docs/monitoring.md ("alert on state, not history") and
the pattern page. New alert rules get a runbook in the same commit (tools/kb.py checks),
which forces the question "what does someone do when this fires?". If the answer is
"nothing, it was already fixed", the rule is measuring history.
