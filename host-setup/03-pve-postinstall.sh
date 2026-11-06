#!/usr/bin/env bash
# Step 3: run ON the Proxmox node as root, e.g. from Windows:
#   scp "C:\Users\Rare Earth\proxmox-lab\03-pve-postinstall.sh" root@10.10.10.10:/root/
#   ssh root@10.10.10.10 'bash /root/03-pve-postinstall.sh'
#
# Does: switch to the free no-subscription repo, full-upgrade, download Ubuntu
# 26.04.1 Desktop (checksum verified), create VM 100 "ubuntu-ws01".
# Read through it before running - every line is fair game in an interview.
set -euo pipefail

UBU_VER="26.04.1"
UBU_ISO="ubuntu-${UBU_VER}-desktop-amd64.iso"
UBU_URL="https://releases.ubuntu.com/${UBU_VER}"
ISO_DIR="/var/lib/vz/template/iso"
VMID=100

echo "==> Checking for the Hyper-V installer boot workaround in GRUB config"
# 04-boot-pve-installer.ps1 boots the installer with rdinit=/bin/sh -- -c "...".
# The installer copies extra boot params into /etc/default/grub.d/installer.cfg, and
# the nested quotes turn that into shell code that breaks update-grub (and so every
# future kernel upgrade). Remove it before apt runs any kernel hooks.
if grep -qs 'rdinit=' /etc/default/grub.d/installer.cfg; then
    mv /etc/default/grub.d/installer.cfg /root/installer.cfg.broken-rdinit
    update-grub
    echo "    removed installer.cfg (backup in /root) and regenerated grub.cfg"
fi

echo "==> Configuring APT repositories (PVE 9 / Debian trixie, deb822 format)"
# Disable the enterprise repos (they need a paid subscription key and 401 otherwise)
for f in /etc/apt/sources.list.d/pve-enterprise.sources /etc/apt/sources.list.d/ceph.sources; do
    if [[ -f "$f" ]] && ! grep -q '^Enabled:' "$f"; then
        echo "Enabled: no" >> "$f"
        echo "    disabled $f"
    fi
done

cat > /etc/apt/sources.list.d/proxmox.sources <<'EOF'
Types: deb
URIs: http://download.proxmox.com/debian/pve
Suites: trixie
Components: pve-no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF

echo "==> Updating system"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get -y full-upgrade

echo "==> Downloading Ubuntu ${UBU_VER} Desktop ISO"
cd "$ISO_DIR"
if [[ ! -f "$UBU_ISO" ]]; then
    wget -q --show-progress "${UBU_URL}/${UBU_ISO}"
fi
wget -q -O SHA256SUMS "${UBU_URL}/SHA256SUMS"
grep " \*\?${UBU_ISO}\$" SHA256SUMS | sha256sum -c -
rm -f SHA256SUMS

echo "==> Creating VM ${VMID} (ubuntu-ws01)"
if qm status "$VMID" &>/dev/null; then
    echo "    VM ${VMID} already exists - skipping"
else
    qm create "$VMID" \
        --name ubuntu-ws01 \
        --ostype l26 \
        --machine q35 \
        --bios ovmf \
        --efidisk0 local-lvm:1,efitype=4m,pre-enrolled-keys=1 \
        --cpu host \
        --cores 4 \
        --memory 8192 \
        --scsihw virtio-scsi-single \
        --scsi0 local-lvm:64,iothread=1,discard=on,ssd=1 \
        --net0 virtio,bridge=vmbr0 \
        --ide2 "local:iso/${UBU_ISO},media=cdrom" \
        --boot 'order=scsi0;ide2' \
        --vga std \
        --agent enabled=1
fi

qm config "$VMID"
echo
echo "Done. Start it with:  qm start ${VMID}"
echo "Then open the console in the web UI: https://10.10.10.10:8006 -> VM 100 -> Console"
