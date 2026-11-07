# One lab workstation: a full clone of the golden image, with its own name, MAC,
# size and cloud-init drive. The only definition of "a workstation VM" in the repo.
#
# Used by terraform/fleet (for_each over inventory/workstations/) and terraform/guest
# (one portal machine per state file). The image comes from `lab image build`
# (ansible/roles/runner/files/lab: image_build); its VM ID is passed in by `lab`.
#
# What happens after creation is not OpenTofu's business: on first boot the clone's
# lab-firstboot service (ansible/roles/pxe/templates/image-user-data.yaml.j2) fetches
# its one-time join password and runs ansible-pull, which joins AD and applies the
# role AD assigns it (docs/boundaries.md has the ownership table).

terraform {
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.120"
    }
  }
}

variable "name" {
  type        = string
  description = "Host name; Proxmox's cloud-init sets it as the machine's hostname."
}
variable "vmid" { type = number }
variable "mac" {
  type        = string
  description = "The DHCP reservation on dc01 keys on this (address plan: ansible/group_vars/all.yml)."
}
variable "image_vmid" {
  type        = number
  description = "VM ID of the golden image template to clone."
}
variable "size" {
  type        = object({ cores = number, memory_mb = number, disk_gb = number })
  description = "From the machine's catalog/ entry."
}
variable "tags" { type = list(string) }
variable "ssh_keys" {
  type        = list(string)
  description = "Authorized keys for the local admin account (labadmin)."
}
variable "settings" {
  type        = any
  description = "ansible/group_vars/all.yml, decoded: node, datastore, bridge."
}

resource "proxmox_virtual_environment_vm" "this" {
  node_name = var.settings.pve_node
  vm_id     = var.vmid
  name      = var.name
  tags      = sort(var.tags) # Proxmox sorts tags; unsorted would show a diff every plan

  on_boot = true # come back by themselves when pve01 restarts

  # Workstations are disposable: on destroy (reimage), power off immediately instead
  # of waiting for a clean shutdown a broken VM may never complete.
  stop_on_destroy = true

  clone {
    vm_id        = var.image_vmid
    full         = true # independent of the template, so old images can be deleted
    datastore_id = var.settings.pve_datastore
  }

  # When cloning, the provider applies its own defaults for anything not set here
  # (e.g. SeaBIOS), so the hardware is spelled out to match the template exactly.
  machine = "q35"
  bios    = "ovmf"
  operating_system {
    type = "l26"
  }
  cpu {
    cores = var.size.cores
  }
  memory {
    dedicated = var.size.memory_mb
  }
  efi_disk {
    datastore_id      = var.settings.pve_datastore
    type              = "4m"
    pre_enrolled_keys = true # Secure Boot with Microsoft's keys (the image boots shim -> GRUB)
  }
  scsi_hardware = "virtio-scsi-single"
  disk {
    interface    = "scsi0"
    datastore_id = var.settings.pve_datastore
    size         = var.size.disk_gb
    discard      = "on"
    ssd          = true
    iothread     = true
  }
  network_device {
    bridge      = var.settings.pve_bridge
    model       = "virtio"
    mac_address = var.mac
  }
  # Without an entropy source, current OVMF builds won't start the network stack
  # (post-PixieFail EDK2). Clones don't network-boot, but they share the template's
  # firmware settings, and a reimage must never be the first time this is wrong.
  rng {
    source = "/dev/urandom"
  }
  boot_order = ["scsi0"]

  # Proxmox's cloud-init drive: the hostname (from name) and the admin's SSH key.
  # Networking isn't here: the image does DHCP on any wired NIC by itself
  # (lab-generalize), so no interface names are involved. Everything else is
  # configuration management's job (ansible-pull), not the image's.
  initialization {
    datastore_id = var.settings.pve_datastore
    interface    = "ide2"
    user_account {
      username = "labadmin"
      keys     = var.ssh_keys
    }
  }

  # The provider waits for the guest agent to report addresses on create and refresh.
  # A clone that is still booting has no agent yet; don't hold the state lock for it.
  agent {
    enabled = true
    timeout = "30s"
  }

  lifecycle {
    # A new golden image applies when a machine is rebuilt (`lab reimage`), not by
    # replacing every workstation the moment the image changes.
    ignore_changes = [clone]
  }
}
