@echo off
chcp 65001 >nul
rem ============================================================
rem  DSH 手机入口代理 —— 手动启动（带黑窗口，方便看口令和报错）
rem
rem  ★ 手机地址不用记固定的 —— 这个脚本会【自动打印当前应该用的地址】
rem    （因为 PC 的 IP 会变：之前是 192.168.10.17，后来变成 192.168.0.39）
rem
rem  用法：双击本文件，它会把「手机打开这个网址」直接印出来。
rem  开机自启靠 start_proxy_hidden.vbs（在「启动」文件夹里）。
rem ============================================================
cd /d D:\ubuntu_iso

set TOKEN=xb7k2m9q
set PORT=3081

echo.
echo ============================================================
echo   DSH 手机入口代理
echo ============================================================
echo.
echo   正在检测本机局域网 IP ...
echo.

rem ★ 用 PowerShell 挑一个「能连板子的」局域网 IP：
rem   排除 127.* / 169.254.* / 192.168.56.*（VirtualBox）/ 192.168.137.*（热点残留）
for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -Command ^
  "(Get-NetIPAddress -AddressFamily IPv4 ^| Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -notlike '192.168.56.*' -and $_.IPAddress -notlike '192.168.137.*' } ^| Select-Object -First 1).IPAddress"`) do set MYIP=%%i

if "%MYIP%"=="" set MYIP=(没检测到，用 ipconfig 看一下)

echo   ┌────────────────────────────────────────────────────┐
echo   │  手机浏览器打开这个网址：                          │
echo   │                                                    │
echo   │     http://%MYIP%:%PORT%/?k=%TOKEN%
echo   │                                                    │
echo   │  ★ 必须在【同一个 WiFi】下                       │
echo   │  ★ 打开一次就会记住，之后不用再输口令              │
echo   └────────────────────────────────────────────────────┘
echo.
echo   口令（万一要手输）: %TOKEN%
echo   监听端口: %PORT%    （代理转发到本机 127.0.0.1:3080 的 DSH）
echo.
echo ============================================================
echo.

python dsh_proxy.py --port %PORT% --token %TOKEN%
pause
