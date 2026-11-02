#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deploy_voice.py —— 部署「系统管家小白」的桌面入口 + 音频工具。

* ui/apps_agent.py, ui/desktop.py, ui/audio_svc.py  -> /home/zynq/ui/
* agent/*.py                                        -> /home/zynq/agent/
* 百度密钥从 ESP 那份源码里读出来，写进 /etc/zynq-agent.env (0600 root)
* 重启 zynq-agent，并做一轮检查

用法: python deploy_voice.py
"""
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import board as B                                              # noqa: E402

ESP_SRC = os.path.join(HERE, "agent", "esp32", "src", "main.cpp")

UI_FILES = ["apps_agent.py", "desktop.py", "audio_svc.py", "fbui.py", "home.py"]
AGENT_FILES = ["audio_client.py", "tts.py", "tools.py", "core.py", "config.py"]


def extract_keys():
    with open(ESP_SRC, encoding="utf-8", errors="replace") as f:
        t = f.read()
    def g(n):
        m = re.search(r'#define\s+%s\s+"([^"]+)"' % n, t)
        return m.group(1) if m else ""
    return g("BAIDU_API_KEY"), g("BAIDU_SECRET_KEY")


def main():
    c = B.conn()
    sftp = c.open_sftp()

    for fn in UI_FILES:
        lp = os.path.join(HERE, "ui", fn)
        if os.path.isfile(lp):
            sftp.put(lp, "/home/zynq/ui/" + fn)
            print("  ui/%s" % fn)
    for fn in AGENT_FILES:
        lp = os.path.join(HERE, "agent", fn)
        if os.path.isfile(lp):
            sftp.put(lp, "/home/zynq/agent/" + fn)
            print("  agent/%s" % fn)
    sftp.close()

    k, s = extract_keys()
    if not k or not s:
        print("!! 没从 %s 里找到百度密钥" % ESP_SRC)
    else:
        env = "BAIDU_API_KEY=%s\nBAIDU_SECRET_KEY=%s\n" % (k, s)
        tmp = os.path.join(HERE, "_baidu.env")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(env)
        sftp = c.open_sftp()
        sftp.put(tmp, "/tmp/_baidu.env")
        sftp.close()
        os.remove(tmp)
        cmd = ("sudo sh -c 'grep -q BAIDU_API_KEY /etc/zynq-agent.env 2>/dev/null || "
               "cat /tmp/_baidu.env >> /etc/zynq-agent.env; "
               "chmod 600 /etc/zynq-agent.env; rm -f /tmp/_baidu.env'; "
               "sudo wc -l /etc/zynq-agent.env; "
               "sudo sh -c 'sed -n \"s/^\\(BAIDU_[A-Z_]*\\)=.*/\\1=<set>/p\" "
               "/etc/zynq-agent.env'")
        print(B.run(cmd))

    print(B.run("sudo systemctl restart zynq-agent; sleep 3; "
                   "systemctl is-active zynq-agent; "
                   "curl -s --max-time 6 http://127.0.0.1:8765/health; echo"))
    print(B.run("cd /home/zynq && python3 -c \""
                   "import sys; sys.path.insert(0,'/home/zynq');"
                   "from agent import tts; print('token ok:', bool(tts.token()))\" 2>&1 | tail -5"))
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
