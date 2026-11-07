# Changing this repository

## Before you push

Run the checks; CI runs exactly the same script, and the lab only follows commits that
pass it:

```sh
pip install -r tools/requirements.txt    # once (plus shellcheck and OpenTofu 1.13)
tools/check                              # everything
tools/check python inventory             # just some groups
```

On mgmt01 there's a ready environment: `PATH=/opt/lab-dev/bin:$PATH tools/check`.

| Group | What it checks |
|---|---|
| `lint-yaml` | yamllint (`.yamllint`) |
| `lint-ansible` | ansible-lint, `moderate` profile (`.ansible-lint`) |
| `lint-shell` | shellcheck on the shell scripts |
| `python` | ruff (`ruff.toml`), and the unit tests in `tests/` |
| `inventory` | `tools/validate_inventory.py`: the fleet and catalogue follow the rules |
| `references` | `tools/check_references.py`: every repository path a file mentions exists |
| `kb` | `tools/kb.py check`: the knowledge base's pages, links and component map are valid, every alert has a runbook, and the generated index is current |
| `tofu` | `tofu fmt` and `tofu validate` for both roots |

## Where things go

- **A setting** (an address, a name, a limit): `ansible/group_vars/all.yml`, once.
  Ansible, OpenTofu and the Python all read it, so it holds plain values only.
- **A file deployed to a server:** in the role that deploys it, `files/` or
  `templates/`. No role reaches into another's directory or outside `ansible/`.
- **A per-workstation thing** (an AD object, a reservation, a password): it belongs to
  `ansible/identity.yml` (`roles/dc_identity`, `roles/join_otp`), which `lab` runs with
  the inventory passed in. Nothing else should create or delete per-machine state.
- **A list of things that changes at runtime:** one file per thing in a directory, not
  lines in a shared file (the fleet, DHCP reservations, join-password rules, guest
  records, operations all work this way). Adding and removing is creating and deleting
  a file; nobody edits anyone else's lines.

## The knowledge base

Every problem fixed gets a page in docs/kb (docs/kb/README.md has the templates and rules):

1. Write `docs/kb/issues/KB-NNNN-<slug>.md` (the next free number) while you fix it: symptom, how
   it was found (`found_by`: monitoring, build, investigation, user, ci or review), root cause,
   fix, verification with the output that proved it, prevention.
2. Link its pattern from docs/kb/patterns, or add a pattern page if none fits.
3. A new alert rule in ansible/roles/monitoring/files/alerts.yml needs a runbook in
   docs/kb/runbooks and a `runbook_url` annotation.
4. `python3 tools/kb.py build`, then commit the fix and its pages together (add the commit hash
   to the page's `commits` in a follow-up commit if you want it exact).

## Comments

Comments are part of the design here: a maintainer should be able to open any file and
learn what it is, where it runs, and what it connects to, without reading the rest.

- **Every deployed file starts with a header** naming where it lands and what deploys
  it, then what it's for:
  `# /usr/local/sbin/dhcp-dns-update on dc01 (roles/dhcp_server)`
- **Say how it fits.** Name the files on either side of an interface by path ("the
  worker reads this log", "set by roles/dc_identity"). `tools/check_references.py`
  fails when a named path stops existing, so these don't rot silently.
- **Explain why, not what.** A comment earns its place when it records a reason, a
  constraint or a failure the code prevents (docs/lessons.md has the stories). Don't
  narrate what the next line obviously does.
- **Section banners** (`# ---- name ----`) for files longer than a screen, so the
  structure shows at a glance.

## Commits

Plain, descriptive messages: what changed and why. The portal's admin page also commits
to `main` (fleet deletes), as "Lab portal".
