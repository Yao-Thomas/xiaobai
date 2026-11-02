# assemble_package.ps1 -- build the delivery package folder from ai_training/
#
# ASCII only (Windows PowerShell 5.1 reads .ps1 as ANSI).
# Layout:
#   AI训练交付包_v1.0/
#     00_先读我.md
#     01_交付物/         model + policy deliverables + acceptance data
#     02_文档/           docs 00..07
#     03_源码/           src/ + tests/
#     04_脚本/           scripts/
#     05_实验记录/       key experiment reports

param([switch]$NoZip)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Pkg = Join-Path (Split-Path -Parent $Root) "AI训练交付包_v1.0"

Write-Host "source : $Root"
Write-Host "package: $Pkg"

function Copy-Tree($from, $to) {
    if (-not (Test-Path $from)) { Write-Host "  [skip] $from"; return }
    New-Item -ItemType Directory -Force $to | Out-Null
    Copy-Item -Recurse -Force (Join-Path $from '*') $to
}

# ---- 01 交付物 ----
Write-Host "`n[1/5] 01_交付物"
$d1 = Join-Path $Pkg "01_交付物"
# ★ 必须先把目标目录建出来：PowerShell 的 Copy-Item 在目标不存在时会把源目录的
#   【内容】倒进目标，而不是创建子目录（第一版就踩了这个，quantized_model 被拍平）
New-Item -ItemType Directory -Force $d1 | Out-Null
foreach ($m in @('quantized_model', 'quantized_model_uniform_mfq',
                 'scope_policy_v4_quantized', 'eq_policy_quantized',
                 'scope_policy_v3_quantized')) {
    $src = Join-Path $Root "deliverables\$m"
    if (Test-Path $src) {
        Copy-Item -Recurse -Force $src (Join-Path $d1 $m)
        Write-Host "  + $m"
    }
}
# 验收数据
$acc = Join-Path $d1 "验收数据"
New-Item -ItemType Directory -Force $acc | Out-Null
foreach ($r in @('wavenet_v3', 'scope_policy_v4', 'eq_policy_v1', 'agent', 'scope_bonus')) {
    $src = Join-Path $Root "runs\$r"
    if (Test-Path $src) {
        $dst = Join-Path $acc $r
        New-Item -ItemType Directory -Force $dst | Out-Null
        Copy-Item -Force (Join-Path $src '*') $dst -ErrorAction SilentlyContinue
    }
}
Write-Host "  + 验收数据"

# ---- 02 文档 ----
Write-Host "`n[2/5] 02_文档"
Copy-Tree (Join-Path $Root "docs") (Join-Path $Pkg "02_文档")

# ---- 03 源码 ----
Write-Host "`n[3/5] 03_源码"
$d3 = Join-Path $Pkg "03_源码"
foreach ($m in @('common', 'train', 'rl', 'agent', 'serve')) {
    Copy-Tree (Join-Path $Root "src\$m") (Join-Path $d3 $m)
}
Copy-Tree (Join-Path $Root "tests") (Join-Path $d3 "tests")

# ---- 04 脚本 ----
Write-Host "`n[4/5] 04_脚本"
$d4 = Join-Path $Pkg "04_脚本"
Copy-Tree (Join-Path $Root "scripts") $d4
# ★ 把临时/调试脚本挪进子目录，正式脚本留在顶层，便于交接
$dbg = Join-Path $d4 "_调试脚本"
New-Item -ItemType Directory -Force $dbg | Out-Null
Get-ChildItem $d4 -File | Where-Object { $_.Name.StartsWith('_') } |
    Move-Item -Destination $dbg -Force -ErrorAction SilentlyContinue
Write-Host ("  正式脚本 {0} 个，调试脚本 {1} 个" -f
    (Get-ChildItem $d4 -File).Count, (Get-ChildItem $dbg -File).Count)

# ---- 05 实验记录 ----
Write-Host "`n[5/5] 05_实验记录"
$d5 = Join-Path $Pkg "05_实验记录"
New-Item -ItemType Directory -Force $d5 | Out-Null
foreach ($f in @('requirements_lock.txt')) {
    $src = Join-Path $Root $f
    if (Test-Path $src) { Copy-Item -Force $src $d5 }
}
# 关键日志（小的）
foreach ($r in @('scope_policy_v1', 'scope_policy_v2', 'scope_policy_v3',
                 'scope_policy_v4', 'wavenet_v3', 'wavenet_v3_stft',
                 'eq_policy_v1', 'agent')) {
    $src = Join-Path $Root "runs\$r"
    if (Test-Path $src) {
        New-Item -ItemType Directory -Force (Join-Path $d5 $r) | Out-Null
        Get-ChildItem $src -File | Where-Object { $_.Length -lt 3MB } |
            Copy-Item -Destination (Join-Path $d5 $r) -Force
    }
}

# ---- 清理 pycache ----
Get-ChildItem -Recurse -Directory -Filter "__pycache__" $Pkg -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Recurse -File $Pkg -Include *.pyc -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

# ---- 统计 ----
Write-Host "`n=== 包内统计 ==="
Get-ChildItem $Pkg -Directory | ForEach-Object {
    $s = (Get-ChildItem -Recurse -File $_.FullName | Measure-Object Length -Sum).Sum
    "{0,-16} {1,5} files  {2,8:N0} KB" -f $_.Name,
        (Get-ChildItem -Recurse -File $_.FullName).Count, ($s / 1KB)
}
$tot = (Get-ChildItem -Recurse -File $Pkg | Measure-Object Length -Sum)
"TOTAL            {0,5} files  {1,8:N0} KB" -f $tot.Count, ($tot.Sum / 1KB)

if (-not $NoZip) {
    $zip = "$Pkg.zip"
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Write-Host "`n压缩 -> $zip"
    Compress-Archive -Path (Join-Path $Pkg '*') -DestinationPath $zip -Force
    "ZIP              {0,8:N0} KB" -f ((Get-Item $zip).Length / 1KB)
}
Write-Host "`npackage done: $Pkg"
