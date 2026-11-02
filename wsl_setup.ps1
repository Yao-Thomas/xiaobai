# wsl_setup.ps1 —— WSL 就绪后：导入 Ubuntu18.04 + 建用户 + 配源 + 装 PetaLinux 依赖
# 用法:  pwsh -File D:\ubuntu_iso\wsl_setup.ps1

$ErrorActionPreference = "Continue"
$DIST   = "Ubuntu-18.04"
$ROOTFS = "D:\ubuntu_iso\ubuntu-18.04-wsl.rootfs.tar.gz"
$VHDDIR = "D:\wsl\Ubuntu-18.04"

function Say($m){ Write-Host "==> $m" }
function WSL([string]$cmd, [string]$user="root"){
    if($user){ wsl.exe -d $DIST -u $user -- bash -lc $cmd } else { wsl.exe -d $DIST -- bash -lc $cmd }
}

Say "1) 检查 WSL 是否可用"
$null = wsl.exe --list --quiet 2>&1
if($LASTEXITCODE -ne 0){ Write-Host "!! WSL 还没启用，请先以管理员运行桌面上的 2-启用WSL2.bat"; exit 1 }

Say "2) 导入发行版 (若未导入)"
$list = (wsl.exe --list --quiet 2>&1 | Out-String)
if($list -notmatch [regex]::Escape($DIST)){
    New-Item -ItemType Directory -Force -Path $VHDDIR | Out-Null
    wsl.exe --import $DIST $VHDDIR $ROOTFS
    if($LASTEXITCODE -ne 0){ Write-Host "!! 导入失败"; exit 1 }
} else { Say "   已存在，跳过导入" }

Say "3) 创建用户 zynq (PetaLinux 不允许 root 安装)"
WSL @'
id zynq >/dev/null 2>&1 || useradd -m -s /bin/bash -G sudo zynq
echo 'zynq:123456' | chpasswd
echo 'zynq ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/zynq
chmod 440 /etc/sudoers.d/zynq
'@

Say "4) 设为默认用户 + 关闭 systemd 依赖"
WSL @'
cat > /etc/wsl.conf <<'EOF'
[user]
default=zynq
[interop]
enabled=true
appendWindowsPath=false
EOF
'@

Say "5) 配置清华 apt 源 (bionic)"
WSL @'
cat > /etc/apt/sources.list <<'EOF'
deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ bionic main restricted universe multiverse
deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ bionic-updates main restricted universe multiverse
deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ bionic-backports main restricted universe multiverse
deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ bionic-security main restricted universe multiverse
EOF
apt-get update -y
'@

Say "6) 安装 PetaLinux 依赖 (含 i386)"
WSL @'
export DEBIAN_FRONTEND=noninteractive
apt-get install -y iproute2 gawk python3 python build-essential gcc git make net-tools \
  libncurses5-dev tftpd zlib1g-dev libssl-dev flex bison libselinux1 gnupg wget git-core \
  diffstat chrpath socat xterm autoconf libtool tar unzip texinfo gcc-multilib automake \
  screen pax gzip cpio python3-pip python3-pexpect xz-utils debianutils iputils-ping \
  python3-git python3-jinja2 libegl1-mesa libsdl1.2-dev pylint3 tftp-hpa tftpd-hpa
dpkg --add-architecture i386
apt-get update -y
apt-get install -y zlib1g:i386 zlib1g-dev:i386 libstdc++6:i386
'@

Say "7) /bin/sh -> bash"
WSL @'
echo "dash dash/sh boolean false" | debconf-set-selections
DEBIAN_FRONTEND=noninteractive dpkg-reconfigure dash
ls -l /bin/sh
'@

Say "8) tftp 目录"
WSL 'mkdir -p /tftpboot && chmod 777 /tftpboot && echo ok'

Say "9) 验证"
WSL 'uname -a; cat /etc/os-release | head -2; which gcc python3 make; ls -l /bin/sh'

Say "完成! WSL 环境就绪。"
