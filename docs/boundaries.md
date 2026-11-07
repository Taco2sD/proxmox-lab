# Who owns what

Three tools touch every workstation. Each piece has exactly one owner, so no two
tools ever manage the same object.

## The contract

The inventory declares which workstations exist: name, VM ID, MAC, IP and role.

- `inventory/workstations.yml`: the hand-maintained fleet (ws01..04). A lab admin
  deleting a fleet machine from the portal removes its line (a commit by the portal).
- `inventory/guests/<host>.yml`: one file per machine requested through the self-service
  portal, written and committed by the portal's worker, with an `owner` field.

OpenTofu and Ansible read both; neither writes them. Changing the fleet means a commit
to the inventory, whether a person or the portal makes it.

## Ownership

| Piece | Owner | Why |
|---|---|---|
| Proxmox VMs: CPU, memory, disks, MAC, RNG, boot order, autostart | OpenTofu (`terraform/`) | Things with an API and a lifecycle. State lets `plan` show drift and lets removing a declaration destroy the VM. |
| AD computer account and its `role-*` group | Ansible | Its lifecycle differs from the VM's: a reimage replaces the VM but keeps the account, because the role lives there. Samba AD also has no first-class Terraform provider. |
| Guest owner's AD user (`OU=Guests`) | Ansible (`ad_guest_users`) | Created with the machine, deleted by `lab prune`; its password lives only on mgmt01. |
| One-time join password | Ansible | A per-build secret, generated at reimage time, not desired state. |
| DHCP reservation (dc01) | Ansible | A line in a config file on a server. |
| DHCP lease of a removed machine | Ansible (`lab prune`, `dhcp_release`) | Ending the lease is what makes the DHCP hook delete the machine's DNS records. |
| Autoinstall host record and OTP access rule (mgmt01) | Ansible | Files on a server. |
| DNS A/PTR records for workstations | dnsmasq's `dhcp-script` on dc01 | Derived from leases at runtime, owned by the DHCP service account. Not declared anywhere. |
| OS install | PXE + autoinstall | The boot pipeline, triggered by a blank disk. |
| Workstation configuration | Ansible (`ansible-pull`, every ~30 min) | Contents of the OS, converged continuously. |
| Portal state: requests, build progress, visitors' passwords | The portal (`/var/lib/lab-portal` on mgmt01) | Runtime state of a service, not desired state. |
| TLS certificates | certbot (VPS, mgmt01, dc01) and Proxmox's ACME client (pve01) | Renewed on a timer; DNS-01 through acme-dns. |

The test for anything new: if deleting its declaration should tear something down,
and it has an API, it belongs to OpenTofu. If it is a file, package or service on a
Linux machine, it belongs to Ansible.

## State and credentials

- OpenTofu state lives on mgmt01 (`/opt/proxmox-lab/terraform/terraform.tfstate`),
  where `lab` runs, and never goes into git (`.gitignore`); it can contain secrets.
- The Proxmox API token belongs to `terraform@pve`, which has VM, datastore, SDN and
  audit roles, not root. On mgmt01 it is in `/etc/proxmox-lab/tofu.env` (root only).
- The portal's git deploy key can write to this one repository and nothing else.
- Each certificate name has an acme-dns account that can change only its own DNS-01
  challenge record. The registrar's API key stays off every lab machine and the VPS.
- None of these, nor visitors' passwords or the Guacamole and session keys, are in git.
