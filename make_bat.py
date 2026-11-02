import io, os

ROOT = r"D:\总文件夹\FPGA2026"

SET = r'''@echo off
title 改系统时间到2020年

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo   需要管理员权限, 正在弹出授权窗口...
    echo   请在弹出窗口里点【是】
    echo.
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo.
echo ==================================================
echo   把系统时间临时改到 2020-06-15 12:00:00
echo   用途: 绕过 Vivado 2018.3 的 2026 年 HLS bug
echo ==================================================
echo.

powershell -NoProfile -Command "$old=Get-Date; $old.ToString('yyyy-MM-dd HH:mm:ss') | Out-File '%~dp0date_backup.txt' -Encoding ASCII; Write-Host ('已保存原时间 -> date_backup.txt : ' + $old.ToString('yyyy-MM-dd HH:mm:ss')); Set-Date -Date '2020-06-15 12:00:00'; Write-Host ''; Write-Host ('现在系统时间: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) -ForegroundColor Green; Write-Host ''; Write-Host 'OK 改好了! 请回去跟 AI 说: 改好了' -ForegroundColor Yellow"

echo.
echo ==================================================
echo   出完 bitstream 后, 双击 恢复时间.bat 恢复
echo ==================================================
echo.
pause
'''

RESTORE = r'''@echo off
title 恢复系统时间

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo   需要管理员权限, 正在弹出授权窗口...
    echo   请在弹出窗口里点【是】
    echo.
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo.
echo ==================================================
echo   恢复系统时间
echo ==================================================
echo.

if exist "%~dp0date_backup.txt" (
    powershell -NoProfile -Command "$old=(Get-Content '%~dp0date_backup.txt').Trim(); Write-Host ('备份的原时间: ' + $old); Set-Date -Date $old; Write-Host ('已恢复: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) -ForegroundColor Green"
) else (
    echo   没找到 date_backup.txt, 改用网络时间同步...
    powershell -NoProfile -Command "Start-Service w32time -ErrorAction SilentlyContinue; w32tm /resync /force 2>$null | Out-Null; Write-Host ('现在时间: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) -ForegroundColor Green"
)

echo.
pause
'''

for name, txt in (("改时间.bat", SET), ("恢复时间.bat", RESTORE)):
    p = os.path.join(ROOT, name)
    # Windows 中文系统用 GBK(936), cmd 读取才不会乱码
    data = txt.replace("\n", "\r\n").encode("gbk", errors="replace")
    with open(p, "wb") as f:
        f.write(data)
    print("  %s -> GBK, %d 字节" % (name, len(data)))

# 验证解码
for name in ("改时间.bat", "恢复时间.bat"):
    p = os.path.join(ROOT, name)
    t = open(p, "rb").read().decode("gbk")
    assert "管理员权限" in t and "Set-Date" in t
    print("  ✅ %s 内容校验通过" % name)
