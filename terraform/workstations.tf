locals {
  workstations = yamldecode(file("${path.module}/../inventory/workstations.yml")).workstations
}

# One VM per inventory entry. The VM is only the hardware: the disk starts blank,
# so the first boot falls through to PXE and the workstation installs itself
# (mgmt01 autoinstall) and configures itself (ansible-pull from this repo).
#
# Reimage:  tofu apply -replace='proxmox_virtual_environment_vm.workstation["ws03"]'
resource "proxmox_virtual_environment_vm" "workstation" {
  for_each = local.workstations

  node_name = "pve01"
  vm_id     = each.value.vmid
  name      = each.key

  on_boot = true # come back by themselves when pve01 restarts

  machine = "q35"
  bios    = "ovmf"

  operating_system {
    type = "l26"
  }

  cpu {
    cores = 2
  }

  memory {
    dedicated = 2048
  }

  efi_disk {
    datastore_id      = "local-lvm"
    type              = "4m"
    pre_enrolled_keys = true # Secure Boot with Microsoft's keys: shim -> GRUB over PXE
  }

  scsi_hardware = "virtio-scsi-single"

  disk {
    interface    = "scsi0"
    datastore_id = "local-lvm"
    size         = 24
    discard      = "on"
    ssd          = true
    iothread     = true
  }

  network_device {
    bridge      = "vmbr0"
    model       = "virtio"
    mac_address = each.value.mac # the DHCP reservation and the PXE host record key on this
  }

  # Without an entropy source, current OVMF builds won't start the network stack
  # (post-PixieFail EDK2), so the VM never offers a PXE boot entry.
  rng {
    source = "/dev/urandom"
  }

  # Disk first, then network: a blank disk falls through to PXE once; after the
  # install the disk wins. Network first would reinstall on every boot.
  boot_order = ["scsi0", "net0"]

  agent {
    enabled = true
  }
}
