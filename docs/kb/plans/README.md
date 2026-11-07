# Action plans

A plan turns a cluster of KB issues into ordered work. Issues say *what is wrong and why*;
patterns say *what kind of wrong it is*; a plan says *what to do, in what order, and how to
back out*.

## How a plan is made

1. **Find the cluster.** Start from docs/kb/INDEX.md: patterns and components ranked by
   issue count, and the open issues. Open issues that share a pattern or a component and
   can be fixed by the same change, or must be fixed in a set order, belong in one plan.
   An issue may appear in more than one plan, but only one plan should own each step.
2. **Order by risk removed per unit of effort,** and put anything with a deadline first.
   Something that protects other steps (a verified backup before touching the AD
   database) comes before them.
3. **Every step is small enough to back out** on its own, and says how in "Risks and
   rollback". A step that can't be backed out says so, and gets a backup or a test first.
4. **"Done when" is observable:** an alert that fires in a test, a command's output, a
   dashboard panel. Not "configured".
5. When a step is finished, tick it, link the commit, and move the issue to `fixed` or
   `mitigated` with a `resolved` date. The plan is `done` when its "Done when" holds.

## Front matter

`plan` (PLAN-NNNN, matches the file name), `title`, `status` (proposed | in-progress |
done), `created`, `issues`, `patterns`, `components`, and optionally `owner`. Sections: Goal,
Why, Steps (a checklist), Risks and rollback, Done when. `tools/kb.py check` enforces this.

## For agents

Before proposing a new plan, read the existing ones: extend a plan whose cluster fits
rather than starting a parallel one. Base each step on evidence in the linked issues, not
on general advice. Don't execute a step marked as the user's call (anything on the Windows
host, deleting data, network changes that could lock people out) without asking.
