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
                                                VPS's sign-in page, LDAPS, Kerberos, AD DNS
 mgmt01                   lab-metrics           the lab's own records: owner, role and power
                          (textfile collector)  of every workstation, last configuration run,
                                                memory budget, reconciler, images, operations
 pve01                    lab-wg-metrics        the WireGuard tunnel's last handshake
```

Prometheus **pulls** every 15 seconds. That's what makes "down" reliable: a target that
doesn't answer is `up == 0` at once, where a push system has to guess from silence.

## How it follows the machines

Prometheus has no Proxmox discovery, so `lab-metrics` (every 30 seconds) writes the
target list for it (`file_sd`): every workstation that is running and has finished its
build, with labels `host`, `owner`, `role`, `kind`, `vmid`. Prometheus re-reads the file
by itself. The Lab overview's per-workstation panels repeat over whatever is in that
list, so they appear and disappear with the machines; the Machine dashboard's picker
is the same list plus the servers.

Hibernated and stopped machines aren't targets (an "is it down?" alert for a machine
that's meant to be off is noise). They still show: in the workstation table, as
hibernated, and in Proxmox's view of the VMs.

## Alerts

`ansible/roles/monitoring/files/alerts.yml`, grouped by what they protect: availability
(targets down, failed probes, failed systemd units), capacity (disks, memory, the
storage pool, the portal's memory budget), correctness (certificates, clock skew,
pending security updates, reboots) and the lab's automation (workstations that stopped
checking in, the reconciler, failed operations, the tunnel). Each says what and where,
and what to look at first.

There's no Alertmanager: firing alerts show on the Lab overview and on Prometheus's
alerts page. In production, Alertmanager would route them to the on-call channel, group
related ones and handle silences during maintenance.

## Changing it

| To change | Edit | Takes effect |
|---|---|---|
| A dashboard | `ansible/roles/monitoring/files/grafana/dashboards/*.json` (Grafana's UI can't save: export the JSON from a copy, commit) | Grafana re-reads within 30 s |
| An alert rule | `files/alerts.yml` | Prometheus reloads (SIGHUP), no restart |
| A scrape job or probe | `templates/prometheus.yml.j2`, `templates/blackbox.yml.j2` | Same |
| A version | `templates/compose.yml.j2` (tag and digest) | Container recreated |

Retention: 30 days or 2 GB, whichever comes first (`/var/lib/lab-monitoring/prometheus`).
