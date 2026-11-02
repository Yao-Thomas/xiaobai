#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diag_freeze.py —— 查为什么 SIGSTOP 之后画面还在变"""
import sys
import time

sys.path.insert(0, ".")
from mc_lab import Board

b = Board()
b.sudo("systemctl stop zynq-desktop zynq-screen-guard; pkill -9 -x python3", 25)
time.sleep(1)
b.sudo("cd /home/zynq/ui && (setsid nohup python3 run_mc.py 90 "
       ">/tmp/mc.log 2>&1 </dev/null &) ; echo go", 25)
time.sleep(8)

print("--- 进程列表 ---")
print(b.sudo("ps -eo pid,ppid,stat,comm,args | grep -E 'python3|run_mc' | grep -v grep", 25))

print("--- 发 SIGSTOP ---")
print(b.sudo("pkill -STOP -x python3; sleep 0.4; echo sent", 25))

print("--- 停住后的进程状态 (STAT 里带 T 才算停住) ---")
print(b.sudo("ps -eo pid,stat,comm | grep python3 | grep -v grep", 25))

print("--- 停住后连读两次显存, 比较 md5 ---")
b.sudo("dd if=/dev/fb0 of=/tmp/a.raw bs=3072 count=600 2>/dev/null", 25)
time.sleep(1.2)
b.sudo("dd if=/dev/fb0 of=/tmp/b.raw bs=3072 count=600 2>/dev/null", 25)
print(b.run("md5sum /tmp/a.raw /tmp/b.raw", 25))

print("--- 谁还在跑 ---")
print(b.sudo("ps -eo pid,stat,comm | grep -vE 'ps|grep' | head -25", 25))

b.sudo("pkill -CONT -x python3", 20)
b.sudo("pkill -9 -f run_mc.py; pkill -9 -x python3; "
       "systemctl start zynq-screen-guard zynq-desktop; echo restored", 30)
b.close()
