@echo off
chcp 65001 >nul
REM ════════════════════════════════════════════════════════════════
REM  build_exe.bat —— 打包 PC 客户端并部署到桌面
REM ════════════════════════════════════════════════════════════════
REM  ★★★ 为什么用 --onedir 而不是 --onefile（2026-10-03 踩了很久）
REM  ────────────────────────────────────────────────────────────────
REM  用 --onefile 打出来的单文件 exe 会被 Windows Defender 判成
REM      Trojan:Win32/Bearfoos.A!ml
REM  （"!ml" = 机器学习启发式，也就是它没有真凭据，纯属猜的）
REM  ⇒ Defender 直接把 exe 【删掉】
REM  ⇒ 用户双击"没反应"，其实是文件已经不存在了
REM  ⇒ 表现就是"板子能用、PC 不行"（板子上跑的是 Python 源码）
REM
REM  为什么 onefile 容易中招：
REM    它把整个 Python 运行时压进一个 exe，运行时自解压到临时目录
REM    再执行 —— 这个行为和很多木马一样，所以启发式引擎容易误报。
REM    --onedir 不解压（_internal 目录就在旁边），一般不会被误判。
REM  ★ 实测：onefile 版被删，onedir 版正常运行。
REM
REM  代价：产物是一个文件夹（约 29 MB）而不是单个文件。
REM        部署时会复制到桌面 + 建一个快捷方式，用户点快捷方式即可。
REM  如果你非要单文件 exe：先以管理员运行 fix_defender.bat 加排除项，
REM        再把下面的 --onedir 改成 --onefile。
REM ════════════════════════════════════════════════════════════════

cd /d D:\ubuntu_iso

echo ══════════════════════════════════════════════════════
echo  打包 PC 客户端 -^> dist\系统管家小白\
echo ══════════════════════════════════════════════════════
echo.

python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [错误] 没装 PyInstaller。先跑： pip install pyinstaller
    pause
    exit /b 1
)

REM ---- 清掉上次的产物 ----
if exist "dist\系统管家小白" rmdir /s /q "dist\系统管家小白"
if exist "dist\系统管家小白.exe" del /q "dist\系统管家小白.exe"
if exist "build\系统管家小白" rmdir /s /q "build\系统管家小白"

echo [1/2] 正在打包（几分钟，别关窗口）...
echo.

python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onedir ^
    --windowed ^
    --name "系统管家小白" ^
    --hidden-import xb_client ^
    --hidden-import xb_audio ^
    --hidden-import xb_pcsr ^
    --add-data "xb_pcsr.ps1;." ^
    --add-data "xb_pcsr_async.ps1;." ^
    --exclude-module numpy ^
    --exclude-module matplotlib ^
    --exclude-module PIL ^
    xb_chat.py

if not exist "dist\系统管家小白\系统管家小白.exe" (
    echo.
    echo [失败] 没看到产物。看上面输出。
    pause
    exit /b 1
)

echo.
echo [2/2] 部署到桌面...
echo.

set "SRC=D:\ubuntu_iso\dist\系统管家小白"
set "DST=%USERPROFILE%\Desktop\系统管家小白"

REM 程序开着就复制不了
tasklist /FI "IMAGENAME eq 系统管家小白.exe" 2>nul | find /i "系统管家小白.exe" >nul
if not errorlevel 1 (
    echo   [注意] 程序正在运行，先关掉它。关完按任意键继续...
    pause >nul
)

if exist "%DST%" rmdir /s /q "%DST%" 2>nul
xcopy /e /i /y /q "%SRC%" "%DST%" >nul 2>&1
if errorlevel 1 (
    echo   [失败] 复制不过去 —— 程序还开着？关掉再双击本文件。
    pause
    exit /b 1
)

REM 建快捷方式（用户点这个，不用进文件夹）
powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell; $l = $ws.CreateShortcut('%USERPROFILE%\Desktop\系统管家小白.lnk'); $l.TargetPath = '%DST%\系统管家小白.exe'; $l.WorkingDirectory = '%DST%'; $l.Save()" >nul 2>&1

echo   产物: %DST%\系统管家小白.exe
echo   快捷方式: %USERPROFILE%\Desktop\系统管家小白.lnk
echo.
echo   ★ 双击桌面上的「系统管家小白」快捷方式即可。
echo   ★ token 留空会自动试（板子默认 u6kCWANi）。
echo   ★ 启动日志: %USERPROFILE%\.xiaobai_chat.log
echo   ★ 建议只开【一个】实例。
echo.
pause
