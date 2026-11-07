# Operating the lab

Written for whoever looks after the lab next. Everything runs from **mgmt01** as root
(`ssh root@10.10.10.6`); the `lab` command is the way in. Its source is
`ansible/roles/runner/files/lab`, with the shared library next to it (`lablib.py`).

## Everyday commands

| Command | What it does | Changes anything? |
|---|---|---|
| `lab status` | Every workstation that should exist, and what Proxmox has for it; orphan VMs; the current golden image | No |
| `lab doctor` | Secrets present, services up, certificates' days left, dc01 and pve01 reachable, reconciler recent | No |
| `lab plan` | What the fleet's OpenTofu run would change | No |
| `lab apply` | Make the fleet match `inventory/workstations/` (asks first; destroys need you to type their names) | Yes |
| `lab reimage ws03 [...]` | Rebuild machines from the current image; they keep their AD account, role and owner | Yes |
| `lab image build [KIND]` | Build new golden images over PXE (headless about 6 minutes, desktop longer), switch to them, delete the old ones | Yes |
| `lab deploy` | Configure the servers (`ansible/site.yml`) | Yes |
| `lab guest create\|delete <host>` | Build or remove one portal machine from its record (the portal's worker normally does this) | Yes |

Every changing command is an **operation**: a record in `/var/lib/lab/ops/` (the admin
page's Activity list), a full log in `/var/log/lab/<id>.log`, and lines in
`/var/lib/lab/audit.jsonl`. Operations the portal starts run as transient systemd units:
`journalctl -u lab-op-<id>`.

## How changes reach the lab

1. Push to `main` (or merge a pull request).
2. GitHub Actions runs `tools/check`. If it passes, it fast-forwards `stable` to that
   commit (`.github/workflows/checks.yml`).
3. On mgmt01, `lab-reconcile.timer` runs `lab reconcile` every minute. When `stable`
   moved, it deploys the servers (`ansible/site.yml`) and applies the fleet. Every 30
   minutes it applies anyway, which repairs drift.
4. Workstations pull `stable` every 30 minutes (`ansible-pull`).

**Configuring a workstation now** instead of waiting for its next pull: on the admin
page, tick the machines and click "Run configuration". The row says Configuring until
the machine reports the run finished. By hand, the same thing through the guest agent
on pve01 (`qm guest exec <vmid> -- systemctl start --no-block ansible-pull.service`), or
`sudo systemctl start ansible-pull` on the machine itself; its log is
`journalctl -u ansible-pull`.

So a commit that fails its checks never reaches the lab. To see where things stand:
`journalctl -u lab-reconcile -n 50`, or the admin page's Activity list.

**Destroys wait for a person.** If a commit removes a fleet machine, the reconciler
stops before destroying it and the admin page shows "Approve destroying …". Deleting a
fleet machine from the admin page commits the removal and approves it in one step.

**A commit that breaks the deploy** is recorded as failed and not retried until the next
commit (or the 30-minute run). Fix forward: push the fix; CI and the reconciler do the
rest.

## The golden images

Workstations are clones of a Proxmox template, one per kind of workstation (`images` in
`ansible/group_vars/all.yml`; `/var/lib/lab/image.json` says which VM is current):

| Image | Template VMs | Source | For |
|-------|--------------|--------|-----|
| headless | 9000 / 9001 | Ubuntu minimal server + the AD client | dev/jump boxes (`kind: headless`) |
| desktop | 9002 / 9003 | full Ubuntu server + Ubuntu Desktop (GNOME) and every desktop role's packages | the graphical workstations (`kind: desktop`) |

Everything is baked in so a clone's first boot only enrolls it (domain join, owner,
one configuration run): deploy speed first. `lab image build [headless|desktop]` makes
new ones (both without an argument, one after the other):

1. points the builder's MAC link at that kind's install record, creates the builder VM
   (9009, MAC from `image_builder`) and starts it; its blank disk makes it network-boot,
2. dc01's DHCP sends it to mgmt01's TFTP (shim, GRUB, `roles/pxe`), GRUB starts the
   Ubuntu installer with the builder's install record (`image-user-data.yaml.j2`),
3. after the install, the builder's first boot installs `lab-firstboot` (what every
   clone runs on its first boot), then `lab-generalize` removes everything
   machine-specific and powers off,
4. `lab` converts it into a template under the free image ID and deletes the old one.

A new image applies to machines as they're rebuilt (`lab reimage`), not all at once.
Rebuild it after changing the image's install record, and now and then for updates
(clones also get security updates through `ansible-pull`).

## Secrets

None are in git. Each lives only where it's used, root-only unless noted.

| Secret | Where | Used by |
|---|---|---|
| Proxmox API token (`terraform@pve`) | mgmt01 `/etc/proxmox-lab/tofu.env` (0600) | OpenTofu, `lab` |
| Runner SSH key (`lab-runner@mgmt01`) | mgmt01 `/root/.ssh/id_ed25519` | Ansible to dc01 and pve01 as `svc-runner` |
| GitHub deploy key (this repository only) | mgmt01 `/root/.ssh/github_deploy` | The admin page's fleet deletes (commits to `main`) |
| labadmin's password hash, the lab's public key | mgmt01 `/root/provision/labadmin.hash`, `/root/pvelab.pub` | The golden image (`roles/pxe`), clones' cloud-init |
| acme-dns accounts | mgmt01 `/etc/lab-portal/acme-dns/lab.json`; dc01 `/etc/acme-dns-client/dc01.json`; pve01 `/root/acme-dns/pve.json`; VPS `/etc/acme-dns/accounts/` | Certificate renewals |
| Portal session key, Guacamole JSON key | mgmt01 `/etc/lab-portal/` (group labportal) | Admin cookie; terminal logins |
| Visitors' passwords | mgmt01 `/var/lib/lab/passwords/` | Their AD account and terminal login |
| OpenTofu state | mgmt01 `/var/lib/lab/tofu/` | Can contain secrets |
| WireGuard keys | pve01 `/etc/wireguard/lab.conf`, VPS | The tunnel |
| Sign-in gate account (`demo`) | VPS `/etc/oauth2-proxy/users.htpasswd` (bcrypt) | The public sign-in page |

`lab doctor` checks that mgmt01's are present.

## Backups and recovery

pve01 backs up **dc01** (VM 105) and **mgmt01** (CT 106) every night at 03:30 and keeps
seven (`roles/pve_backups`). Workstations aren't backed up: they're rebuilt from the
image, the catalogue and the inventory.

- **A workstation is broken:** `lab reimage <host>`.
- **mgmt01 is lost:** restore CT 106 from the Proxmox UI (Backup). Everything that
  isn't in git (OpenTofu states, guest records, secrets) is in that backup.
- **dc01 is lost:** restore VM 105. Workstations reconnect by themselves.
- **The reconciler is stuck:** `systemctl status lab-reconcile`, its log, then
  `lab doctor`.
- **Pause the reconciler** (maintenance, a migration): `touch /var/lib/lab/reconcile.paused`;
  remove the file to resume. A deployment doesn't undo it (stopping the timer would be
  undone by the next deploy), and `lab doctor` reports it.

## Rebuilding mgmt01 from nothing

The parts that are set up by hand once, before Ansible can take over:

1. Proxmox: create the unprivileged LXC (Ubuntu), `pct set 106 --features nesting=1,keyctl=1`
   (Docker needs it), MAC `mgmt01_mac` from `ansible/group_vars/all.yml`.
2. Packages: `ansible-core`, OpenTofu, `tftpd-hpa`, `nginx`; shim and GRUB in `/srv/tftp`,
   the installer kernel and initrd in `/srv/tftp/ubuntu-26.04`, the ISO in `/var/www/html`.
3. Clone this repository to `/opt/proxmox-lab` and check out `stable`.
4. Put the secrets above in place.
5. `ansible-playbook -i ansible/servers.yml ansible/bootstrap.yml` for each server (see its
   header), then `lab deploy`.

## Adding a server or a role

- **A catalogue role:** add `catalog/<name>.yml` (copy one; `tools/validate_inventory.py`
  checks it). The first machine with that role creates its AD group `role-<name>`.
- **A fleet machine:** add `inventory/workstations/<host>.yml` (see that directory's
  README) and push.
- **A server to manage:** add it to `ansible/servers.yml`, run `bootstrap.yml` for it,
  then add a play to `ansible/site.yml`.
