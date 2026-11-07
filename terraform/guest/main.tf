# One portal machine. Each has its own state file
# (mgmt01:/var/lib/lab/tofu/guest-<host>.tfstate), like a Coder workspace: builds and
# deletes run independently and in parallel, and one broken machine can't block the
# rest. Run by `lab guest create|delete` (ansible/roles/runner/files/lab), which passes
# these variables from the machine's record on mgmt01 (/var/lib/lab/guests/<host>.json).

terraform {
  backend "local" {}
}

provider "proxmox" {}

variable "host" { type = string }
variable "vmid" { type = number }
variable "mac" { type = string }
variable "role" { type = string }
variable "owner" { type = string }
variable "images" { type = map(number) } # golden image per kind (headless, desktop)
variable "ssh_keys" { type = list(string) }

locals {
  root     = "${path.module}/../.."
  settings = yamldecode(file("${local.root}/ansible/group_vars/all.yml"))
  catalog  = yamldecode(file("${local.root}/catalog/${var.role}.yml"))
}

# image_vmid: the role's kind picks the golden image. lab checks it exists before a
# build; a delete doesn't need it (the clone source only matters when the VM is created).
module "workstation" {
  source = "../modules/workstation"

  name       = var.host
  vmid       = var.vmid
  mac        = var.mac
  size       = local.catalog.size
  tags       = ["lab-workstation", "guest", "role-${var.role}", "owner-${var.owner}"]
  image_vmid = lookup(var.images, local.catalog.kind, 0)
  ssh_keys   = var.ssh_keys
  settings   = local.settings
}
