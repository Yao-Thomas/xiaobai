# ============================================================================
# create_vm.ps1 —— 自动创建 Ubuntu 16.04 虚拟机
#   名字 ubuntu16-petalinux，内存 8G / 4 核 / 150G 动态盘，自动挂 ISO。
#   VirtualBox 实际装在 D:\VirualBox\
# ============================================================================
$ErrorActionPreference = "Continue"

# 找 VBoxManage（你的机器装在 D:\VirualBox\）
$VBox = "D:\VirualBox\VBoxManage.exe"
if (-not (Test-Path $VBox)) { $VBox = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" }
if (-not (Test-Path $VBox)) { $VBox = "C:\Program Files (x86)\Oracle\VirtualBox\VBoxManage.exe" }
if (-not (Test-Path $VBox)) { Write-Error "找不到 VBoxManage.exe"; exit 1 }
Write-Host "VBoxManage: $VBox"

$VM   = "ubuntu16-petalinux"
$BASE = "D:\ubuntu_iso\vm"
$VDI  = "$BASE\$VM.vdi"
$ISO  = "D:\ubuntu_iso\ubuntu-16.04.7-desktop-amd64.iso"
New-Item -ItemType Directory -Force -Path $BASE | Out-Null

# 幂等：同名 VM 先删
$vms = & $VBox list vms
if ($vms -match [regex]::Escape("`"$VM`"")) {
    Write-Host "已存在同名 VM，先删除..."
    & $VBox controlvm $VM poweroff 2>$null
    Start-Sleep -Seconds 2
    & $VBox unregistervm $VM --delete 2>$null
}

Write-Host "== 创建 VM =="
& $VBox createvm --name $VM --ostype Ubuntu_64 --register
& $VBox modifyvm $VM --memory 8192 --cpus 4 --vram 64
& $VBox modifyvm $VM --boot1 dvd --boot2 disk --boot3 none --boot4 none
& $VBox modifyvm $VM --nic1 nat --natdnshostresolver1 on --audio none
& $VBox modifyvm $VM --clipboard-mode bidirectional
# Hyper-V 主机(雷电模拟器占了虚拟化)下，给 Linux guest 开 Hyper-V 半虚拟化，兼容&提速
& $VBox modifyvm $VM --paravirtprovider hyperv
# 开启嵌套分页/长模式等（默认即可）
& $VBox modifyvm $VM --nestedpaging on

Write-Host "== 创建 150G 动态磁盘 =="
& $VBox createmedium disk --filename $VDI --size 153600 --variant Standard

Write-Host "== 挂 SATA + 磁盘 + ISO =="
& $VBox storagectl $VM --name SATA --add sata --controller IntelAhci --portcount 2
& $VBox storageattach $VM --storagectl SATA --port 0 --device 0 --type hdd --medium $VDI
if (Test-Path $ISO) {
    & $VBox storageattach $VM --storagectl SATA --port 1 --device 0 --type dvddrive --medium $ISO
    Write-Host "ISO 已挂载: $ISO"
} else { Write-Warning "ISO 不存在: $ISO" }

Write-Host ""
Write-Host "=== VM '$VM' 创建完成 ==="
& $VBox showvminfo $VM --machinereadable 2>$null | Select-String -Pattern "^(name|memory|cpus|SATA-0-0|SATA-1-0)=" | ForEach-Object { $_.Line }
