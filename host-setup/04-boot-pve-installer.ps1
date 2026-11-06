#Requires -RunAsAdministrator
# Boots the Proxmox VE installer on a Hyper-V Gen 2 VM with no typing required.
#
# Why: the PVE initrd's /init snapshots /sys modaliases ONCE, before hv_vmbus has
# enumerated its child devices, so it never loads hv_storvsc (the SCSI DVD -> "no
# device with valid ISO found") or hyperv_keyboard (no keyboard in its rescue shell).
# The GRUB menu itself runs on UEFI firmware drivers, so it DOES receive keys.
#
# This script power-cycles the VM, waits for the GRUB menu (it has no timeout),
# then uses Hyper-V's WMI synthetic keyboard (the same API as Clipboard > Type
# clipboard text) to drop to the GRUB prompt and boot the installer kernel with a
# tiny pre-init that loads both drivers and then execs the real /init.

param(
    [string]$VMName = 'pve01',
    [int]$BootWaitSeconds = 15,
    [switch]$TerminalUI          # use the text-mode installer instead of the graphical one
)

$ErrorActionPreference = 'Stop'
$ns = 'root\virtualization\v2'

$vm = Get-VM -Name $VMName
if ($vm.State -ne 'Off') {
    Write-Host "Turning off $VMName (it's stuck in the initrd anyway)..."
    Stop-VM -Name $VMName -TurnOff -Force
}
$dvd = Get-VMDvdDrive -VMName $VMName
if (-not $dvd.Path) { throw "No ISO in $VMName's DVD drive - attach it first." }

Start-VM -Name $VMName
Write-Host "Started $VMName; waiting $BootWaitSeconds s for the GRUB menu..."
Start-Process vmconnect.exe -ArgumentList 'localhost', $VMName
Start-Sleep -Seconds $BootWaitSeconds

$cs = Get-CimInstance -Namespace $ns -ClassName Msvm_ComputerSystem -Filter "ElementName='$VMName'"
$kb = Get-CimAssociatedInstance -InputObject $cs -ResultClassName Msvm_Keyboard

function Send-Key([int]$vk) {
    $r = Invoke-CimMethod -InputObject $kb -MethodName TypeKey -Arguments @{ keyCode = [uint32]$vk }
    if ($r.ReturnValue -ne 0) { throw "TypeKey($vk) failed: $($r.ReturnValue)" }
    Start-Sleep -Milliseconds 300
}
function Send-Line([string]$text) {
    $r = Invoke-CimMethod -InputObject $kb -MethodName TypeText -Arguments @{ asciiText = $text }
    if ($r.ReturnValue -ne 0) { throw "TypeText failed: $($r.ReturnValue)" }
    Start-Sleep -Milliseconds 300
    Send-Key 0x0D   # Enter
}

$extra = if ($TerminalUI) { ' proxtui' } else { '' }
# Double quotes keep the -c script as ONE argument; GRUB re-quotes it when it builds
# the kernel command line. Everything after "--" is handed to init (/bin/sh) as argv.
$preinit = 'PATH=/sbin:/bin:/usr/sbin:/usr/bin; modprobe hyperv_keyboard; modprobe hv_storvsc; sleep 3; exec /init'
$linux   = "linux /boot/linux26 ro ramdisk_size=16777216 rw quiet splash=silent$extra rdinit=/bin/sh -- -c `"$preinit`""

Write-Host "Opening the GRUB command line and booting the installer..."
Send-Key 0x43        # 'c' -> grub> prompt
Start-Sleep -Seconds 1
Send-Line $linux
Send-Line 'initrd /boot/initrd.img'
Start-Sleep -Seconds 1
Send-Line 'boot'

Write-Host @"

Sent. In the VM window you should see:
  testing device '/dev/sr0' for ISO
  found Proxmox VE ISO
and then the installer. If the screen shows the grub> prompt with an error instead,
screenshot it. If it simply sat at the menu, re-run with -BootWaitSeconds 25.
"@ -ForegroundColor Cyan
