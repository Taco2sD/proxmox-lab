#!/usr/bin/env bash
# Step 3: run ON the Proxmox node as root, e.g. from Windows:
#   scp "C:\Users\Rare Earth\proxmox-lab\host-setup\03-pve-postinstall.sh" root@10.10.10.10:/root/
#   ssh root@10.10.10.10 'bash /root/03-pve-postinstall.sh'
#
# Does: repair the GRUB config the Gen 2 installer workaround leaves behind, switch to
# the free no-subscription repository, full-upgrade. What comes after (mgmt01
# rebuilt, dc01 restored from backup) is in docs/operations.md.
# Read through it before running - every line is fair game in an interview.
set -euo pipefail

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

echo "Done. Next: mgmt01 (docs/operations.md, \"Rebuilding mgmt01 from nothing\")."
