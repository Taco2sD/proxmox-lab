---
id: KB-0003
title: dc01's systemd-networkd-wait-online failed at every boot (it asked a disabled systemd-resolved for DNS)
status: fixed
found_by: monitoring
signal: SystemdUnitsFailed
found: 2026-11-07
resolved: 2026-11-07
severity: medium
hosts: [dc01]
components: [samba-ad, ad-dns, dhcp]
patterns: [implicit-dependency-on-disabled-service]
commits: []
related: [KB-0004]
---
## Symptom

On the first day of monitoring, `SystemdUnitsFailed` showed dc01 with one failed unit:
`systemd-networkd-wait-online.service`, failed since the boot of 2026-11-06 17:18 with
`Could not create manager: No such file or directory`. The network itself was fine
(`networkctl`: ens18 routable, configured).

## How it was found

The SystemdUnitsFailed alert (node_exporter's systemd collector) and the Lab overview's
firing-alerts table, the first evening Prometheus ran.

## Root cause

Not a boot race, though it looked like one. The boot journal one line earlier says:

```
systemd-networkd-wait-online[997]: Failed to connect to io.systemd.Resolve.Monitor: No such file or directory
systemd-networkd-wait-online[997]: Could not create manager: No such file or directory
```

- netplan 1.2's generator writes a drop-in for wait-online
  (`/run/systemd/generator.late/systemd-networkd-wait-online.service.d/10-netplan.conf`) whose
  command is `systemd-networkd-wait-online --any --dns -o routable -i ens18`. It adds `--dns`
  because the installer's netplan file (`/etc/netplan/00-installer-config.yaml`) still lists
  a nameserver (1.1.1.1).
- `--dns` makes wait-online (systemd 259) ask systemd-resolved, over its
  `io.systemd.Resolve.Monitor` socket, whether a DNS server is reachable.
- systemd-resolved is off on dc01: Samba's internal DNS owns port 53, and resolved was turned
  off by hand during the DC's provisioning (2026-11-05 19:04, journal of boot -1).
  `/etc/resolv.conf` is a static file pointing at dc01 itself.

The boot before that change (2026-11-05 18:52, resolved still running) finished
wait-online normally. Every boot since then fails it, and `systemctl start
systemd-networkd-wait-online` reproduced the failure on 2026-11-07.

Why it matters on a DC: `network-online.target` only *wants* wait-online, so it is reached
at once when wait-online fails. samba-ad-dc and dnsmasq (both `After=network-online.target`)
then start without waiting for the network; at the 2026-11-06 boot they started 30 ms after
the failure. That worked only because dc01's address is static and comes up quickly. With a
slower link (DHCP, a bond, a VLAN, a busy host after a power cut) Samba would have bound its
sockets before the address existed, the classic "DC up but not answering" after a reboot.

## Fix

`ansible/roles/lab_dns` (DNS on dc01):

- writes down that systemd-resolved stays off (it was a hand-made decision);
- adds `/etc/systemd/system/systemd-networkd-wait-online.service.d/20-lab-no-resolved.conf`,
  which sorts after netplan's `10-netplan.conf` and replaces its command with
  `systemd-networkd-wait-online --any -o routable`: wait for a routable interface, not for DNS
  (dc01 *is* the DNS server).

Applied by hand on dc01 exactly as the role does it, then `systemctl reset-failed`.

## Verification

```
$ systemctl cat systemd-networkd-wait-online | grep -E '^# /|ExecStart'
# /run/systemd/generator.late/systemd-networkd-wait-online.service.d/10-netplan.conf
ExecStart=/lib/systemd/systemd-networkd-wait-online --any --dns -o routable -i ens18
# /etc/systemd/system/systemd-networkd-wait-online.service.d/20-lab-no-resolved.conf
ExecStart=
ExecStart=/usr/lib/systemd/systemd-networkd-wait-online --any -o routable
$ sudo systemctl start systemd-networkd-wait-online; echo $?
0
$ systemctl show systemd-networkd-wait-online -p Result
Result=success
$ systemctl --failed --no-legend
$                                   # empty; samba-ad-dc and dnsmasq active
```

Prometheus: `count by (host) (node_systemd_unit_state{state="failed",host="dc01"} == 1)`
returns nothing. Not verified by a reboot (dc01 is the only DC); the next planned reboot
should show wait-online finishing before samba-ad-dc starts (`journalctl -b -o short-precise
-u systemd-networkd-wait-online -u samba-ad-dc`).

## Prevention

- The drop-in and "resolved stays off" are now in the role, so a rebuilt dc01 gets both.
- SystemdUnitsFailed catches any unit that fails at boot, which is how this surfaced.
- Left as is: the installer's dead `nameservers: 1.1.1.1` in the netplan file (nothing reads it
  while resolved is off). Removing it would also stop netplan adding `--dns`, but it means
  editing and re-generating the DC's network configuration; worth doing in a maintenance
  window, together with a reboot to confirm the ordering.
