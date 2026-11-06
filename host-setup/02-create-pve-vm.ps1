#Requires -RunAsAdministrator
# Step 2: build the Hyper-V side of the lab.
#   - Internal vSwitch "LabNAT" + Windows NAT on 10.10.10.0/24 (host = 10.10.10.1 = gateway)
#   - Gen 2 VM "pve01" with nested virtualization, static RAM, MAC spoofing (so guests
#     inside Proxmox can talk through vmbr0), Proxmox ISO attached.
# Safe to re-run: each step checks whether it is already done.

$ErrorActionPreference = 'Stop'

$VMName     = 'pve01'
$SwitchName = 'LabNAT'
$HostIP     = '10.10.10.1'
$Prefix     = '10.10.10.0/24'
$VMRoot     = 'O:\ProxmoxLab\vms'
$IsoPath    = 'O:\ProxmoxLab\iso\proxmox-ve_9.2-1.iso'
$vCPU       = 4
$RAM        = 12GB      # static - dynamic memory is incompatible with nested virt
$DiskSize   = 256GB     # dynamic VHDX, only consumes what's used

if (-not (Test-Path $IsoPath)) { throw "ISO not found at $IsoPath" }

# --- Network: internal switch + NAT ---------------------------------------
if (-not (Get-VMSwitch -Name $SwitchName -ErrorAction SilentlyContinue)) {
    New-VMSwitch -Name $SwitchName -SwitchType Internal | Out-Null
    Write-Host "Created vSwitch $SwitchName"
}
$ifAlias = "vEthernet ($SwitchName)"
if (-not (Get-NetIPAddress -InterfaceAlias $ifAlias -IPAddress $HostIP -ErrorAction SilentlyContinue)) {
    New-NetIPAddress -InterfaceAlias $ifAlias -IPAddress $HostIP -PrefixLength 24 | Out-Null
    Write-Host "Assigned $HostIP/24 to $ifAlias"
}
if (-not (Get-NetNat -Name $SwitchName -ErrorAction SilentlyContinue)) {
    New-NetNat -Name $SwitchName -InternalIPInterfaceAddressPrefix $Prefix | Out-Null
    Write-Host "Created NAT $SwitchName for $Prefix"
}

# --- VM ---------------------------------------------------------------------
if (Get-VM -Name $VMName -ErrorAction SilentlyContinue) {
    Write-Host "VM $VMName already exists - skipping creation." -ForegroundColor Yellow
} else {
    # Gen 2 (UEFI, synthetic devices). Note: the Proxmox installer's initrd does not
    # load hv_storvsc on its own, so the SCSI DVD is invisible to it at first - see
    # the install notes for how to load it before the ISO search.
    New-VM -Name $VMName -Generation 2 -MemoryStartupBytes $RAM `
        -Path $VMRoot -NewVHDPath "$VMRoot\$VMName\$VMName.vhdx" -NewVHDSizeBytes $DiskSize `
        -SwitchName $SwitchName | Out-Null

    Set-VM -Name $VMName -StaticMemory -ProcessorCount $vCPU `
        -AutomaticCheckpointsEnabled $false -CheckpointType Standard

    # The key nested-virt settings
    Set-VMProcessor -VMName $VMName -ExposeVirtualizationExtensions $true
    Get-VMNetworkAdapter -VMName $VMName | Set-VMNetworkAdapter -MacAddressSpoofing On

    # Proxmox's installer is fine without Secure Boot; avoids shim/cert surprises
    Set-VMFirmware -VMName $VMName -EnableSecureBoot Off

    $dvd = Add-VMDvdDrive -VMName $VMName -Path $IsoPath -Passthru
    Set-VMFirmware -VMName $VMName -FirstBootDevice $dvd

    Write-Host "Created VM $VMName ($vCPU vCPU, $($RAM/1GB) GB RAM, $($DiskSize/1GB) GB disk)" -ForegroundColor Green
}

Get-VMProcessor -VMName $VMName | Select-Object VMName, Count, ExposeVirtualizationExtensions | Format-Table
Get-VMNetworkAdapter -VMName $VMName | Select-Object VMName, SwitchName, MacAddressSpoofing | Format-Table

Write-Host @"
Next:
  1. Start-VM $VMName ; vmconnect localhost $VMName
  2. In the installer use these network settings (there is NO DHCP on this subnet):
       Hostname : pve01.lab.internal
       IP/CIDR  : 10.10.10.10/24
       Gateway  : 10.10.10.1
       DNS      : 1.1.1.1
  3. After it reboots: eject the ISO  ->  Get-VMDvdDrive -VMName $VMName | Set-VMDvdDrive -Path `$null
  4. Browse to https://10.10.10.10:8006  (user: root, realm: Linux PAM)
"@ -ForegroundColor Cyan
