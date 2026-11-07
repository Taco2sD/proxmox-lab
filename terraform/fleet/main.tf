# The fleet: one workstation per file in inventory/workstations/. Run by `lab apply`,
# `lab reimage` and `lab reconcile` (ansible/roles/runner/files/lab: fleet_apply),
# never by hand: lab passes the image and key variables and runs identity before and
# after (ansible/identity.yml).
#
# State: mgmt01:/var/lib/lab/tofu/fleet.tfstate (lab passes the path to `tofu init`).
# Portal machines are not here; each has its own state (terraform/guest).

terraform {
  backend "local" {}
}

provider "proxmox" {}

variable "images" { type = map(number) } # golden image per kind (headless, desktop)
variable "ssh_keys" { type = list(string) }

locals {
  root      = "${path.module}/../.."
  settings  = yamldecode(file("${local.root}/ansible/group_vars/all.yml"))
  catalog   = { for f in fileset("${local.root}/catalog", "*.yml") : trimsuffix(f, ".yml") => yamldecode(file("${local.root}/catalog/${f}")) }
  inventory = "${local.root}/inventory/workstations"
  fleet     = { for f in fileset(local.inventory, "*.yml") : trimsuffix(f, ".yml") => yamldecode(file("${local.inventory}/${f}")) }
}

module "workstation" {
  source   = "../modules/workstation"
  for_each = local.fleet

  name       = each.key
  vmid       = each.value.vmid
  mac        = each.value.mac
  size       = local.catalog[each.value.role].size
  tags       = ["lab-workstation", "fleet", "role-${each.value.role}"]
  image_vmid = lookup(var.images, local.catalog[each.value.role].kind, 0)
  ssh_keys   = var.ssh_keys
  settings   = local.settings
}

# 2026-11-07: the VMs moved into the module (they were a resource in this root). Keeps
# ws03/ws04 from being destroyed and recreated by the move itself; safe to delete once
# no state anywhere has the old addresses.
moved {
  from = proxmox_virtual_environment_vm.workstation["ws03"]
  to   = module.workstation["ws03"].proxmox_virtual_environment_vm.this
}
moved {
  from = proxmox_virtual_environment_vm.workstation["ws04"]
  to   = module.workstation["ws04"].proxmox_virtual_environment_vm.this
}
