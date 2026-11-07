terraform {
  required_version = ">= 1.8" # OpenTofu

  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.120"
    }
  }
}

# Credentials come from the environment, never from files in this repo. `lab` reads
# them from mgmt01:/etc/proxmox-lab/tofu.env (root only):
#   PROXMOX_VE_ENDPOINT   https://pve.radicallydecent.com:8006/  (AD DNS: pve01, verified TLS)
#   PROXMOX_VE_API_TOKEN  terraform@pve!tofu=<secret>  (PVEVMAdmin, PVEDatastoreUser,
#                                                       PVESDNUser, PVEAuditor; not root)
