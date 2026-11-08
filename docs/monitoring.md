# Monitoring

Prometheus collects, Grafana shows, alert rules say when someone has to act. All of it
runs on mgmt01 and follows the lab as it changes: a new workstation is on the
dashboards within a minute of its first configuration run, and a deleted or hibernated
one drops off without raising a false alarm.

Open it from the admin page (**Monitoring**) or from a machine in My lab (**Metrics**):

| Page | What it's for |
|---|---|
| `/grafana/d/lab-overview` | **Lab overview**: firing alerts, service checks, the hypervisor's VMs, every workstation, the servers' key services, the automation |
| `/grafana/d/lab-machine?var-host=ws35` | **Machine**: one server or workstation in detail, inside (node_exporter) and out (Proxmox) |
| `/prometheus/alerts` | Every alert rule and its state |
| `/prometheus/targets`, `/prometheus/service-discovery` | What Prometheus scrapes right now, and where that list came from |
| [docs/kb/](kb/README.md) | The knowledge base: a runbook per alert, every issue found and how it was fixed (both dashboards link to it) |

Anyone past the portal's sign-in gate can look; nobody can edit in Grafana. The
dashboards are JSON in git, deployed like everything else.

## What feeds it

```
 every machine            node_exporter :9100   CPU, memory, disks, network, systemd units,
 (roles/node_exporter)                          clock offset, pending apt updates
 pve01 API                pve-exporter          every VM as Proxmox sees it (running or not),
 (roles/pve_monitoring)                         storage pools; read-only token
 mgmt01                   blackbox              the services probed the way a user meets them:
                                                portal, Guacamole, Grafana, Proxmox API, the
                                                VPS's sign-in page, LDAPS, Kerberos, AD DNS;
                                                and per workstation, SSH and (desktops) the
                                                Desktop button's path via pve01's console relay
 mgmt01                   lab-metrics           the lab's own records: owner, role and power
                          (textfile collector)  of every workstation, last configuration run,
                                                memory budget, reconciler, images, operations
 pve01                    lab-wg-metrics        the WireGuard tunnel's last handshake
 pve01                    lab-guest-metrics     what each guest is (container or VM) and the
                                                limits pve01 enforces on it: its Proxmox config
                                                and its cgroup (CPU weight, cpuset, memory and
                                                swap limits, process limit, pressure, OOM kills)
```

A guest can't be trusted to say what it is: a container runs on pve01's kernel and even
reads pve01's hardware data (mgmt01's node_exporter reports "Microsoft Corporation Virtual
Machine", which is pve01 under Hyper-V), and its limits are set above what it can see. So
the Machine dashboard takes "Kind" and the whole Limits section from pve01.

Prometheus **pulls** every 15 seconds. That's what makes "down" reliable: a target that
doesn't answer is `up == 0` at once, where a push system has to guess from silence.

## How it follows the machines

Prometheus has no Proxmox discovery, so `lab-metrics` (every 30 seconds) writes the
target list for it (`file_sd`): every workstation that is running and has finished its
build, with labels `host`, `owner`, `role`, `kind`, `vmid`. Prometheus re-reads the file
by itself. The Lab overview's per-workstation panels repeat over whatever is in that
list, so they appear and disappear with the machines; the Machine dashboard's picker
is the same list plus the servers.

From the same records it writes a second list, `access.json`: the ways people reach each
of those machines. blackbox probes them every minute (job `probes-access`): SSH on every
workstation (the browser terminal is SSH too) and, on desktop machines, the Desktop
button's path through pve01's console relay. Both probes stop at the banner, so nobody's
open session notices. The Lab overview shows them as "Access paths"; a path that fails
while its machine is up raises AccessPathDown (docs/kb/issues/KB-0160-workstation-access-paths-unprobed.md).

Hibernated and stopped machines aren't targets (an "is it down?" alert for a machine
that's meant to be off is noise). They still show: in the workstation table, as
hibernated, and in Proxmox's view of the VMs.

## Alerts

`ansible/roles/monitoring/files/alerts.yml`, grouped by what they protect: availability
(targets down, failed probes, failed systemd units), capacity (disks, memory, the
storage pool, the portal's memory budget), correctness (certificates, clock skew,
pending security updates, reboots) and the lab's automation (workstations that stopped
checking in, the reconciler, failed operations nobody has put right, the tunnel). Each
says what and where, and what to look at first, and links its runbook
(`runbook_url`: docs/kb/runbooks/, one page per rule: what it means, the first five
minutes, known causes, and the issues it has caught before). A new rule needs its
runbook in the same commit; `tools/kb.py check` (part of `tools/check`) fails without it.

Two design rules came out of the first day's alerts (both in the knowledge base):

- **Alert on state, not history.** "Operations failed in the last 24 hours" kept firing
  for failures already put right (KB-0006). `OperationFailureUnresolved` fires only while
  the latest operation on a subject (a machine, an image kind, the release) is a failure;
  a later success on the same subject clears it. An operation stopped by hand counts as
  failed: what it was doing didn't get done.
- **One alert per thing someone fixes.** A failed-unit alert per unit turned one leaking
  template unit into ~1,700 alerts (KB-0007); `SystemdUnitsFailed` is one alert per
  machine with a count, and the Machine dashboard lists the units.

There's no Alertmanager: firing alerts show on the Lab overview and on Prometheus's
alerts page. In production, Alertmanager would route them to the on-call channel, group
related ones and handle silences during maintenance.

## Changing it

| To change | Edit | Takes effect |
|---|---|---|
| A dashboard | `ansible/roles/monitoring/files/grafana/dashboards/*.json` (Grafana's UI can't save: export the JSON from a copy, commit) | Grafana re-reads within 30 s |
| An alert rule | `files/alerts.yml`, and its runbook in `docs/kb/runbooks/` | Prometheus reloads (SIGHUP), no restart |
| A scrape job or probe | `templates/prometheus.yml.j2`, `templates/blackbox.yml.j2` | Same |
| A version | `templates/compose.yml.j2` (tag and digest) | Container recreated |

Retention: 30 days or 2 GB, whichever comes first (`/var/lib/lab-monitoring/prometheus`).
