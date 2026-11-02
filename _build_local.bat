@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
cl /nologo /utf-8 /O2 /LD /Fe:"D:\ubuntu_iso\mcrender_local.dll" "D:\ubuntu_iso\mcrender.c" /link /DEF:"D:\ubuntu_iso\mcrender.def"
