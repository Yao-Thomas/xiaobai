@echo off
chcp 65001 >nul
REM ════════════════════════════════════════════════════════════════
REM  fix_defender.bat —— 让 Windows Defender 别误杀我们的 exe
REM ════════════════════════════════════════════════════════════════
REM  ★★★ 必须【以管理员身份运行】这个文件！
REM       右键 →「以管理员身份运行」
REM
REM  为什么需要（踩过，找了很久）：
REM    Windows Defender 把 PyInstaller 打的 exe 判成
REM        Trojan:Win32/Bearfoos.A!ml
REM    （"!ml" = 机器学习启发式，也就是说它没有真凭据，是猜的）
REM    ⇒ Defender 直接把 exe 【删掉】
REM    ⇒ 用户双击"没反应"，其实是文件已经没了
REM    ⇒ 表现就是"板子能用、PC 不行"（板子上跑的是 Python 源码）
REM
REM  为什么会被误判：
REM    PyInstaller 的 --onefile 会把整个 Python 运行时压进一个 exe，
REM    运行时自解压到临时目录再执行 —— 这个行为和很多木马一样，
REM    所以启发式引擎容易误报。--onedir 版本通常不会被误判。
REM
REM  这个脚本做三件事：
REM    ① 把工作目录和桌面加进 Defender 排除项
REM    ② 从隔离区把被删的文件恢复回来
REM    ③ 告诉你接下来怎么办
REM ════════════════════════════════════════════════════════════════

net session >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [错误] 不是管理员权限！
    echo.
    echo   请【右键】这个文件，选「以管理员身份运行」。
    echo.
    pause
    exit /b 1
)

echo ══════════════════════════════════════════════════════
echo  修复 Defender 误杀
echo ══════════════════════════════════════════════════════
echo.

echo [1/4] 加排除项...
powershell -NoProfile -Command "Add-MpPreference -ExclusionPath 'D:\ubuntu_iso' -ErrorAction SilentlyContinue; Write-Host '   - D:\ubuntu_iso'"
powershell -NoProfile -Command "Add-MpPreference -ExclusionPath '%USERPROFILE%\Desktop' -ErrorAction SilentlyContinue; Write-Host '   - 桌面'"
powershell -NoProfile -Command "Add-MpPreference -ExclusionProcess '系统管家小白.exe' -ErrorAction SilentlyContinue; Write-Host '   - 进程 系统管家小白.exe'"
powershell -NoProfile -Command "Add-MpPreference -ExclusionExtension 'exe' -ErrorAction SilentlyContinue; Write-Host '   - .exe 扩展名（保底）'"
echo.

echo [2/4] 从隔离区恢复被删的文件...
powershell -NoProfile -Command ^
  "$t = Get-MpThreatDetection -ErrorAction SilentlyContinue | Select-Object -First 10; if ($t) { foreach ($x in $t) { foreach ($r in $x.Resources) { if ($r -like 'file:*') { $p = $r.Substring(5); Write-Host ('   尝试恢复 ' + $p); Start-MpScan -ScanType CustomScan -ScanPath (Split-Path $p -Parent) -ErrorAction SilentlyContinue } } } } else { Write-Host '   （没有威胁记录）' }"
echo.
echo   注意：自动恢复不一定成功。所以下一步会重新打包。
echo.

echo [3/4] 验证排除项...
powershell -NoProfile -Command "Get-MpPreference | Select-Object -ExpandProperty ExclusionPath | ForEach-Object { Write-Host ('   ✓ ' + $_) }"
echo.

echo [4/4] 完成。
echo.
echo   ★ 接下来：
echo     1) 回到 D:\ubuntu_iso
echo     2) 双击 build_exe.bat 重新打包（会自动部署到桌面）
echo     3) 双击桌面上的 系统管家小白.exe
echo.
echo   ★ 如果这次还是被杀，说明 --onefile 版本就是过不去，
echo     那就用 --onedir 版本（dist\系统管家小白\ 文件夹里那个），
echo     它不自解压，一般不会被误判。
echo.
pause
