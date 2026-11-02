import os

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

echo   [1/3] 停掉并禁用 Windows 时间服务
echo         (否则它会自动把时间同步回去)
net stop w32time >nul 2>&1
sc config w32time start= disabled >nul 2>&1
echo         完成

echo.
echo   [2/3] 改系统时间
powershell -NoProfile -Command "$old=Get-Date; $old.ToString('yyyy-MM-dd HH:mm:ss') | Out-File '%~dp0date_backup.txt' -Encoding ASCII; Write-Host ('        已保存原时间: ' + $old.ToString('yyyy-MM-dd HH:mm:ss')); Set-Date -Date '2020-06-15 12:00:00'"

echo.
echo   [3/3] 确认
powershell -NoProfile -Command "Write-Host ('        现在系统时间: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) -ForegroundColor Green"

echo.
echo   Windows 时间服务已禁用, 时间不会再被自动改回去
echo.
echo ==================================================
echo   现在回去跟 AI 说一声, 它会开始出流
echo   出完后双击 恢复时间.bat (会重新启用时间服务)
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
echo   恢复系统时间 + 重新启用时间服务
echo ==================================================
echo.

echo   [1/3] 恢复时间
if exist "%~dp0date_backup.txt" (
    powershell -NoProfile -Command "$old=(Get-Content '%~dp0date_backup.txt').Trim(); Write-Host ('        备份的原时间: ' + $old); Set-Date -Date $old"
) else (
    echo         没找到 date_backup.txt, 稍后用网络同步
)

echo.
echo   [2/3] 重新启用 Windows 时间服务
sc config w32time start= auto >nul 2>&1
net start w32time >nul 2>&1
echo         完成

echo.
echo   [3/3] 用网络时间同步校正
w32tm /resync /force >nul 2>&1
powershell -NoProfile -Command "Write-Host ('        现在系统时间: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) -ForegroundColor Green"

echo.
pause
'''

for name, txt in (("改时间.bat", SET), ("恢复时间.bat", RESTORE)):
    p = os.path.join(ROOT, name)
    data = txt.replace("\n", "\r\n").encode("gbk", errors="replace")
    with open(p, "wb") as f:
        f.write(data)
    print("  %s -> GBK %d 字节" % (name, len(data)))

for name in ("改时间.bat", "恢复时间.bat"):
    t = open(os.path.join(ROOT, name), "rb").read().decode("gbk")
    assert "w32time" in t
    print("  ✅ %s 校验通过 (含 w32time 处理)" % name)
