@echo off
chcp 65001 >nul
REM ════════════════════════════════════════════════════════════════
REM  deploy_exe.bat —— 把 dist 里最新的 exe 部署到桌面
REM ════════════════════════════════════════════════════════════════
REM  什么时候用：
REM    程序正开着的时候 build_exe.bat 复制不过去（文件被占用），
REM    这时先关掉程序，再双击本文件即可。
REM
REM  ★ 为什么单独做这个（踩过，代价很大）：
REM    用户双击的是【桌面】上那个 exe，而我一直在改 dist\ 里的。
REM    结果我修了几个 bug、重新打包好几次，用户测来测去
REM    测的都是旧版本 —— 白折腾半天。
REM    ⇒ 以后打包完就自动部署（build_exe.bat 已经会做），
REM      万一当时程序开着没成功，用这个补一下。
REM ════════════════════════════════════════════════════════════════

set "SRC=D:\ubuntu_iso\dist\系统管家小白.exe"
set "DST=%USERPROFILE%\Desktop\系统管家小白.exe"
set "BAK=%USERPROFILE%\Desktop\系统管家小白.exe.bak_上一次"

echo ══════════════════════════════════════════════════════
echo  部署最新版到桌面
echo ══════════════════════════════════════════════════════

if not exist "%SRC%" (
    echo [错误] 找不到 %SRC%
    echo        先在 D:\ubuntu_iso 下双击 build_exe.bat 打包
    pause
    exit /b 1
)

echo  源文件:
for %%F in ("%SRC%") do echo     %%~fF   %%~zF 字节   %%~tF
echo.

REM ---- 先看程序是不是开着 ----
tasklist /FI "IMAGENAME eq 系统管家小白.exe" 2>nul | find /i "系统管家小白.exe" >nul
if not errorlevel 1 (
    echo [注意] 系统管家小白.exe 正在运行，文件被占用，复制会失败。
    echo.
    echo        请先【关掉程序窗口】，然后按任意键继续...
    pause >nul
)

REM ---- 备份旧的 ----
if exist "%DST%" (
    copy /y "%DST%" "%BAK%" >nul 2>&1
    if errorlevel 1 (
        echo   [警告] 备份失败（文件还开着？）
    ) else (
        echo   已备份旧版 -^> %BAK%
    )
)

REM ---- 复制 ----
copy /y "%SRC%" "%DST%" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [失败] 复制不过去 —— 程序还开着。关掉程序再试一次。
    pause
    exit /b 1
)

echo.
echo   ✓ 部署成功
for %%F in ("%DST%") do echo     %%~fF   %%~zF 字节   %%~tF
echo.
echo   ★ 现在双击桌面这个就是最新版了。
echo   ★ 启动日志: %USERPROFILE%\.xiaobai_chat.log
echo   ★ 建议只开【一个】实例 —— 开多个会各自刷新，日志会乱。
echo.
pause
