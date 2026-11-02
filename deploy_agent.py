#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 agent/ 部署到 Zynq 板子, 装成 systemd 服务, 并跑一次真实任务。

用法:
    python deploy_agent.py            # 部署 + 单命令测试 + 起服务 + /health
    python deploy_agent.py --serve-only
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import board                       # noqa: E402
import broot                       # noqa: E402

AGENT = os.path.join(HERE, "agent")
REMOTE = "/home/zynq/agent"

# ESP32 那份代码里已经在用的 key（src/main.cpp 的 DEEPSEEK_KEY）
API_KEY = "YOUR_DEEPSEEK_API_KEY_HERE"
MODEL = "deepseek-chat"


def deploy_files():
    broot.srun("install -d -o zynq -g zynq -m 0755 " + REMOTE, quiet=True)
    n = 0
    for fn in sorted(os.listdir(AGENT)):
        if not fn.endswith(".py"):
            continue
        local = os.path.join(AGENT, fn)
        tmp = "/tmp/_ag_" + fn
        board.put(local, tmp)
        broot.srun("install -o zynq -g zynq -m 0644 %s %s/%s"
                   % (tmp, REMOTE, fn), quiet=True)
        n += 1
    print("上传 %d 个文件 -> %s" % (n, REMOTE))


def write_env():
    """key 放 /etc/zynq-agent.env (0600 root), 不写进用户目录"""
    body = "DEEPSEEK_API_KEY=%s\nAGENT_MODEL=%s\n" % (API_KEY, MODEL)
    local = os.path.join(HERE, "_agent.env")
    with open(local, "w", newline="\n") as f:
        f.write(body)
    board.put(local, "/tmp/_agent.env")
    broot.srun("install -m 0600 -o root -g root /tmp/_agent.env "
               "/etc/zynq-agent.env && rm -f /tmp/_agent.env", quiet=True)
    os.remove(local)
    print("写入 /etc/zynq-agent.env (0600)")


def install_service():
    local = os.path.join(AGENT, "zynq-agent.service")
    board.put(local, "/tmp/_zynq-agent.service")
    broot.srun("install -m 0644 /tmp/_zynq-agent.service "
               "/etc/systemd/system/zynq-agent.service && systemctl daemon-reload",
               quiet=True)
    print("安装 zynq-agent.service")


def main():
    print("HOST =", board.HOST)
    deploy_files()
    write_env()
    install_service()

    print("\n===== 1) 板子上列工具")
    broot.srun("su - zynq -c 'cd /home/zynq && python3 -m agent.main --tools'",
               use_sudo=True)

    print("\n===== 2) 板子上真跑一个任务（要和板子自身状态有关）")
    task = ("看一下 /home/zynq/ui 目录里有多少个 .py 文件，"
            "找出其中最大的那个，告诉我是哪个文件、多少字节")
    broot.srun("su - zynq -c \"cd /home/zynq && "
               "set -a; . /etc/zynq-agent.env; set +a; "
               "python3 -m agent.main '%s'\"" % task, use_sudo=True,
               timeout=300)

    print("\n===== 3) 起 HTTP 服务")
    broot.srun("systemctl enable --now zynq-agent.service && sleep 6 && "
               "systemctl is-active zynq-agent.service && "
               "curl -s --max-time 10 http://127.0.0.1:8765/health")

    print("\n===== 4) 通过网络调 /voice（模拟 ESP32 那边）")
    broot.srun("curl -s --max-time 120 -X POST http://127.0.0.1:8765/voice "
               "-H 'Content-Type: application/json' "
               "-d '{\"text\":\"现在的内存用了多少？用一句话回答\"}'")

    print("\n===== 5) 服务日志")
    broot.srun("tail -20 /var/log/zynq-agent.log")


if __name__ == "__main__":
    main()
