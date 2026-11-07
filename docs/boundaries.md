# Who owns what

Several tools touch every workstation. Each piece has exactly one owner, so no two
tools ever manage the same object.

## The contract

What exists is declared in two places, read by the same code (`lablib.desired()`):

- `inventory/workstations/<host>.yml`: the fleet, one file per machine, in git.
- `/var/lib/lab/guests/<host>.json` on mgmt01: machines requested through the portal,
  written by the portal's worker. Runtime state, not code (docs/self-service.md).

What a workstation *is* comes from `catalog/<role>.yml`. Settings (addresses, names,
limits) come from `ansible/group_vars/all.yml`. OpenTofu and Ansible read all of these;
neither writes them.

## Ownership

| Piece | Owner | Why |
|---|---|---|
| The VM: clone of the golden image, CPU, memory, disk, MAC, cloud-init drive | OpenTofu (`terraform/modules/workstation`; state per tier: fleet, or one per guest) | Things with an API and a lifecycle. State lets `plan` show drift, and removing a declaration destroys the VM. |
| The golden image (Proxmox template) | `lab image build` (PXE + autoinstall, `roles/pxe`) | Built, not declared: an image is the output of an install. |
| AD computer account, its `role-*` group, `managedBy` | Ansible (`roles/dc_identity`, via `ansible/identity.yml`) | Outlives the VM: a rebuild keeps the account, and with it the role and owner. Samba AD has no Terraform provider. |
| A guest owner's AD account (`OU=Guests`) | Ansible (`roles/dc_identity`) | Created with the machine, deleted with it; its password lives only on mgmt01. |
| One-time join password | Ansible (`roles/dc_identity` sets it, `roles/join_otp` publishes it) | A per-build secret, generated when a machine is (re)built, not desired state. |
| DHCP reservation (one file per machine, dc01) | Ansible (`roles/dc_identity`) | A file on a server. |
| DHCP lease of a removed machine | Ansible (`roles/dc_identity`, `dhcp_release`) | Ending the lease is what makes the DHCP hook delete the machine's DNS records. |
| DNS A/PTR records for workstations | dnsmasq's `dhcp-script` on dc01 | Derived from leases at runtime, owned by the DHCP service account. Not declared anywhere. |
| First-boot enrolment | `lab-firstboot` in the image | Fetches the join password, runs ansible-pull once. |
| Workstation configuration | Ansible (`ansible-pull` of `stable`, every ~30 min) | Contents of the OS, converged continuously. |
| Servers' configuration (dc01, mgmt01, pve01) | Ansible (`ansible/site.yml`, applied by the reconciler) | Files, packages and services on servers. |
| Operations, requests, build progress, visitors' passwords | `lab` and the portal (`/var/lib/lab` on mgmt01) | Runtime state of a service. |
| TLS certificates | certbot (VPS, mgmt01, dc01) and Proxmox's ACME client (pve01) | Renewed on a timer; DNS-01 through acme-dns. |

The test for anything new: if deleting its declaration should tear something down,
and it has an API, it belongs to OpenTofu. If it is a file, package or service on a
Linux machine, it belongs to Ansible. If it's about one workstation, it goes through
`ansible/identity.yml`, which `lab` runs with the inventory passed in.

## State and credentials

- OpenTofu state lives on mgmt01 (`/var/lib/lab/tofu/`) and never goes into git; it can
  contain secrets. It's in mgmt01's nightly backup.
- The Proxmox API token belongs to `terraform@pve`, which has VM, datastore, SDN and
  audit roles, not root. On mgmt01 it is in `/etc/proxmox-lab/tofu.env` (root only).
- Automation reaches dc01 and pve01 as `svc-runner`: key-only, the runner's key only,
  only from mgmt01's address (`ansible/bootstrap.yml`).
- The portal's git deploy key can write to this one repository and nothing else.
- Each certificate name has an acme-dns account that can change only its own DNS-01
  challenge record. The registrar's API key stays off every lab machine and the VPS.
- None of these, nor visitors' passwords or the Guacamole and session keys, are in git.
  `docs/operations.md` lists every secret and where it lives.
