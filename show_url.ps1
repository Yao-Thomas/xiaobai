# show_url.ps1 -- 显示手机入口的当前网址 + 服务状态，并把网址复制到剪贴板
$ErrorActionPreference = "SilentlyContinue"
$root = "D:\ubuntu_iso"
Set-Location $root
function Line($s) { Write-Host $s }

Line ""
Line "============================================================"
Line "   手机入口 - 当前状态"
Line "============================================================"
Line ""

$pub = $null
if (Test-Path "$root\tunnel_url.txt") {
    $pub = (Get-Content "$root\tunnel_url.txt" -Encoding UTF8 | Select-Object -First 1).Trim()
}
$proxy = netstat -ano | Select-String ":3081.*LISTENING"
$cf    = Get-Process cloudflared -ErrorAction SilentlyContinue

Line "  [服务状态]"
if ($proxy) { Line "    OK  反向代理   正在监听 3081" }
else        { Line "    --  反向代理   没在跑，需要双击 start_proxy.bat 重启" }
if ($cf)    { Line ("    OK  公网隧道   cloudflared PID " + ($cf.Id -join ',')) }
else        { Line "    --  公网隧道   没在跑，需要重启" }
Line ""

Line "  [在外面 / 用流量]  公网网址:"
Line ""
if ($pub) {
    $full = "$pub/?k=xb7k2m9q"
    Line "      $full"
    Line ""
    try { Set-Clipboard -Value $full; Line "  (已复制到剪贴板，可以直接粘贴到手机)" } catch { }
} else {
    Line "      还没生成，隧道没在跑"
}
Line ""
Line "  [手机开着热点时更快]  局域网网址:"
Line ""
Line "      http://192.168.10.17:3081/?k=xb7k2m9q"
Line ""
Line "============================================================"
Line ""
Read-Host "按回车关闭"