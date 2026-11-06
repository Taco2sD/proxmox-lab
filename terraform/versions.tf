terraform {
  required_version = ">= 1.8" # OpenTofu (for_each in import blocks)

  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.120"
    }
  }
}

# Credentials come from the environment, never from files in this repo:
#   PROXMOX_VE_ENDPOINT   https://10.10.10.10:8006/
#   PROXMOX_VE_API_TOKEN  terraform@pve!tofu=<secret>   (roles: PVEVMAdmin, PVEDatastoreUser,
#                                                         PVESDNUser, PVEAuditor; not root)
#   PROXMOX_VE_INSECURE   true   (Proxmox's self-signed certificate)
provider "proxmox" {}
