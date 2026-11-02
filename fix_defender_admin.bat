@echo off
chcp 65001 >nul
rem ============================================================
rem  fix_defender_admin.bat —— 一次性解决 Defender 误杀
rem
rem  ★ 为什么要管理员：
rem    Add-MpPreference（加排除项）需要管理员权限。
rem    普通权限运行会报 "拒绝访问"，脚本会明确告诉你。
rem
rem  ★ 用法：右键这个文件 →「以管理员身份运行」
rem ============================================================

net session >nul 2>&1
if errorlevel 1 (
    echo.
    echo ============================================================
    echo   ★ 需要管理员权限
    echo ============================================================
    echo.
    echo   请关掉这个窗口，然后：
    echo     右键 fix_defender_admin.bat -^> 以管理员身份运行
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  正在给 Defender 加排除项
echo ============================================================
echo.

set D1=%USERPROFILE%\Desktop\系统管家小白
set D2=D:\ubuntu_iso\dist
set D3=D:\ubuntu_iso

echo [1/3] 排除目录（桌面客户端）
powershell -NoProfile -Command "Add-MpPreference -ExclusionPath '%D1%' -ErrorAction SilentlyContinue; Add-MpPreference -ExclusionPath '%D2%' -ErrorAction SilentlyContinue; Add-MpPreference -ExclusionPath '%D3%' -ErrorAction SilentlyContinue"
echo      done

echo [2/3] 排除进程（系统管家小白.exe / python）
powershell -NoProfile -Command "Add-MpPreference -ExclusionProcess '系统管家小白.exe' -ErrorAction SilentlyContinue; Add-MpPreference -ExclusionProcess 'python.exe' -ErrorAction SilentlyContinue; Add-MpPreference -ExclusionProcess 'pythonw.exe' -ErrorAction SilentlyContinue"
echo      done

echo [3/3] 排除扩展名（.exe 不在其中，太危险；排除 .lnk 的父目录已覆盖）
echo      跳过（目录排除已经覆盖）

echo.
echo ============================================================
echo  当前排除项：
echo ============================================================
powershell -NoProfile -Command "$p = Get-MpPreference; Write-Host '  目录:'; $p.ExclusionPath | ForEach-Object { Write-Host ('    ' + $_) }; Write-Host '  进程:'; $p.ExclusionProcess | ForEach-Object { Write-Host ('    ' + $_) }"

echo.
echo ============================================================
echo  完成！现在 exe 不会再被删了。
echo  （如果之前被删过，重新跑一次 build_exe.bat 部署即可）
echo ============================================================
echo.
pause
