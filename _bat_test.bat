@echo off
echo step1 > D:\ubuntu_iso\_bat_test.log
set PY=C:\Users\姚恩奇\AppData\Local\Programs\Python\Python313\python.exe
echo step2 PY=%PY% >> D:\ubuntu_iso\_bat_test.log
if not exist "%PY%" (echo PY_MISSING >> D:\ubuntu_iso\_bat_test.log & exit /b 2)
echo step3 >> D:\ubuntu_iso\_bat_test.log
cd /d "D:\ubuntu_iso\_ai_handover_v2\AI波形分析交付包_v2.0\03_源码"
echo step4 cwd=%CD% >> D:\ubuntu_iso\_bat_test.log
start "" /b "%PY%" -c "import sys; print('hello from python', sys.version)" >> D:\ubuntu_iso\_bat_test.log 2>&1
echo step5 >> D:\ubuntu_iso\_bat_test.log
exit /b 0
