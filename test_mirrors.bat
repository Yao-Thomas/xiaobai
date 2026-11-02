@echo off
rem 测几个 GitHub 镜像下载 cloudflared 的速度，挑最快的
setlocal enabledelayedexpansion
cd /d D:\ubuntu_iso
set TARGET=cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
set /a N=0
for %%M in (
  "https://gh-proxy.com/"
  "https://ghfast.top/"
  "https://gh.llkk.cc/"
  "https://github.moeyy.xyz/"
  "https://ghproxy.net/"
  "https://gh.ddlc.top/"
) do (
  set /a N+=1
  echo.
  echo === 镜像 !N!: %%~M ===
  curl.exe -L --max-time 15 -o test_!N!.bin -w "  速度: %%{speed_download} B/s   已下: %%{size_download} 字节   状态: %%{http_code}\n" "%%~Mhttps://github.com/%TARGET%" 2>&1 | findstr /C:"速度"
)
echo.
echo === 清理测试文件 ===
del test_*.bin 2>nul
endlocal
