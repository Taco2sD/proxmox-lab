# Who owns what

Three tools touch every workstation. Each piece has exactly one owner, so no two
tools ever manage the same object.

## The contract

`inventory/workstations.yml` declares which workstations exist: name, VM ID, MAC,
IP and role. Both tools read it; neither writes it. Changing the fleet means editing
that file in git.

## Ownership

| Piece | Owner | Why |
|---|---|---|
| Proxmox VMs: CPU, memory, disks, MAC, RNG, boot order, autostart | OpenTofu (`terraform/`) | Things with an API and a lifecycle. State lets `plan` show drift and lets removing a declaration destroy the VM. |
| AD computer account and its `role-*` group | Ansible | Its lifecycle differs from the VM's: a reimage replaces the VM but keeps the account, because the role lives there. Samba AD also has no first-class Terraform provider. |
| One-time join password | Ansible | A per-build secret, generated at reimage time, not desired state. |
| DHCP reservation (dc01) | Ansible | A line in a config file on a server. |
| Autoinstall host record and OTP access rule (mgmt01) | Ansible | Files on a server. |
| DNS A/PTR records for workstations | dnsmasq's `dhcp-script` on dc01 | Derived from leases at runtime, owned by the DHCP service account. Not declared anywhere. |
| OS install | PXE + autoinstall | The boot pipeline, triggered by a blank disk. |
| Workstation configuration | Ansible (`ansible-pull`, every ~30 min) | Contents of the OS, converged continuously. |

The test for anything new: if deleting its declaration should tear something down,
and it has an API, it belongs to OpenTofu. If it is a file, package or service on a
Linux machine, it belongs to Ansible.

## State and credentials

- OpenTofu state never goes into git (`.gitignore`); it can contain secrets.
- The Proxmox API token belongs to `terraform@pve`, which has VM, datastore, SDN
  and audit roles, not root. It is read from `PROXMOX_VE_API_TOKEN` in the environment.
