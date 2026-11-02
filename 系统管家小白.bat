@echo off
chcp 65001 >nul
rem ============================================================
rem  系统管家小白.bat —— 不依赖 exe 的启动方式（备用）
rem
rem  ★ 为什么要有这个：
rem    Windows Defender 老是把打包好的 exe 当成木马删掉
rem    （Trojan:Win32/Bearfoos.A!ml —— ML 启发式误报）。
rem    exe 一被删，桌面图标就点不开了。
rem    这个 bat 直接用 Python 跑源码，不会被杀。
rem
rem  ★ 前提：电脑上装了 Python（本机有 Python 3.13）
rem ============================================================

set PY=%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe
if not exist "%PY%" set PY=pythonw

cd /d D:\ubuntu_iso
start "" "%PY%" xb_chat.py
