#Requires -RunAsAdministrator
# Step 1: enable the full Hyper-V role (hypervisor platform is already on via WSL2,
# but the management service + PowerShell module are not). Requires a reboot.

$feature = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All
if ($feature.State -eq 'Enabled') {
    Write-Host "Hyper-V is already enabled. Go straight to 02-create-pve-vm.ps1" -ForegroundColor Green
    return
}

Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -All -NoRestart
Write-Host ""
Write-Host "Hyper-V enabled. REBOOT NOW, then run 02-create-pve-vm.ps1 from an elevated PowerShell." -ForegroundColor Yellow
