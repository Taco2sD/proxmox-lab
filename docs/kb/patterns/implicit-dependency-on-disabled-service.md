---
pattern: implicit-dependency-on-disabled-service
title: A service is turned off on purpose, and something generated or packaged still depends on it
components: [dc01, samba-ad, ad-dns, time-sync, sssd]
---
## What happens

A host deliberately runs without a standard service (systemd-resolved on a DC whose own DNS
owns port 53, a time daemon replaced by another, a desktop service on a server). Turning it
off is fine; the trouble is the units that still assume it exists. They're often not written
by anyone on the team: generators (netplan, systemd's own), package defaults and drop-ins
rebuilt at every boot. They fail quietly, usually at boot, and whatever is ordered after them
carries on as if they had succeeded.

## How to spot it

- A unit failing with "No such file or directory" or "connection refused" for a socket of
  another service: `journalctl -b -u <unit>` usually names it (`io.systemd.Resolve.Monitor`,
  `/run/systemd/resolve/...`).
- `systemctl cat <unit>` shows drop-ins from `/run/systemd/generator*`: those are rewritten at
  every boot, so editing them by hand doesn't stick.
- Prometheus: `node_systemd_unit_state{state="failed"} == 1` right after a reboot; the
  SystemdUnitsFailed alert.
- Before turning a service off: `systemctl list-dependencies --reverse <service>` and grep the
  generator output (`/run/systemd/generator*`) for its name.

## How to fix

Override the dependent unit with a drop-in in `/etc/systemd/system/<unit>.d/` that sorts after
the generated one (higher number) and replaces only what's wrong (for `ExecStart`, reset it
with an empty `ExecStart=` first). Keep it in the role that owns the decision to turn the
service off, next to the task that keeps it off.

## How to prevent

- Write down every "this host runs without X" decision as a task in its role (state: stopped,
  enabled: false) with the reason. A hand-made change is invisible to the next person.
- After such a change, reboot once in a maintenance window and check `systemctl --failed`
  and the order of the services that matter (`journalctl -b -o short-precise`).

<!-- kb:generated:start -->
<!-- kb:generated:end -->
