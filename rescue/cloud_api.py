#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cloud_api.py —— 云协同统一入口（板子侧 HTTP 服务）

════════════════════════════════════════════════════════════════════
它是什么
════════════════════════════════════════════════════════════════════
按《10_云协同接口约定单.md》实现的板子侧服务。客户端（EXE / APK）只调它。

用户明确要求过：**云协同 = 文件传输 + 远程硬件操作**（不是聊天管理）。
所以这里六块：
    ① 发现与信息      板子信息、局域网发现
    ② 文件传输        分块上传、断点下载、列目录
    ③ 远程硬件操作    读/写寄存器、温度、服务、日志
    ④ 变更历史        变更单 + 一键回滚
    ⑤ 对话            文本/语音 + 会话管理 + 本地/云端切换
    ⑥ 构建任务        发起"改 FPGA"

════════════════════════════════════════════════════════════════════
设计约束（都是踩过坑换来的）
════════════════════════════════════════════════════════════════════
1. **只用标准库** —— 板子上不装任何 pip 包（http.server / json / base64…）
2. **读 PL 寄存器必须 fork 子进程** —— 读没映射的地址会 SIGBUS 打死整个服务
   （这个坑今天踩了两次）
3. **不抛 HTML 错误页** —— 客户端要能直接显示 error 字段
4. **路径白名单** —— 远程文件操作不能被用来读写系统关键文件
5. **写操作全部审计** —— 谁、什么时候、做了什么
6. **token 鉴权** —— 除 /health 外都要带

════════════════════════════════════════════════════════════════════
用法
════════════════════════════════════════════════════════════════════
    sudo python3 cloud_api.py                 # 前台跑（调试）
    sudo python3 cloud_api.py --port 8768
    sudo python3 cloud_api.py --selftest      # 不起服务，只自检各模块能不能用
"""
import argparse
import base64
import datetime
import glob
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------------------------------------------------------------- 配置
CONF_FILE = "/etc/xiaobai-cloud.json"
DEFAULT_CONF = {
    "token": "xb7k2m9q",
    "port": 8768,
    "enable_write": True,
    "discover_port": 8769,
}

AUDIT_FILE = "/var/lib/xiaobai-cloud/audit.jsonl"
UPLOAD_DIR = "/var/lib/xiaobai-cloud/uploads"

# ★ 路径白名单：远程文件操作只能碰这些
ALLOW_ROOTS = [
    "/home/zynq/Music",
    "/home/zynq/fpga_jobs",
    "/home/zynq/wave_dataset",
    "/home/zynq/ui",
    "/home/zynq/agent",
    # ★★★ 接收区（2026-10-03）：PC 端「📥 传到接收区」落这里，
    #   板子上的「传输助手」App 看的就是这个目录。
    #   虽然 /home/zynq 已经涵盖了它，但单独列出来意图更清楚 ——
    #   以后要是有人收紧白名单，不至于把这个目录误伤掉。
    "/home/zynq/received",
    "/home/zynq",
    "/tmp",
    "/var/log",
    "/var/lib/xiaobai",
    "/var/lib/xiaobai-cloud",
    "/mnt/boot",
]
# 只读的根
READONLY_ROOTS = ["/var/log"]
# /mnt/boot 只允许碰 system.bit*
BOOT_ALLOW = re.compile(r"^/mnt/boot/(system\.bit.*|BOOT\.BIN.*)$")

# PL 地址表（和 07_接口约定单 一致）
PL_MAP = {
    "lcd_id": 0x41200000, "axi_gpio": 0x41210000,
    "gpu_0": 0x43CB0000, "scope_0": 0x43CC0000,
    "cnn_conv_pool": 0x43CD0000, "cnn_fc": 0x43CE0000,
    "audio_fmt": 0x43C50000, "i2s_rx": 0x43C60000,
    "i2s_tx": 0x43C70000, "pwm_backlight": 0x43C00000,
}

LOGS = {
    "desktop": "/var/log/zynq-desktop.log",
    "thermal": "/var/log/thermal_guard.log",
}
SERVICES = ["zynq-desktop", "zynq-audio", "zynq-agent",
            "thermal-guard", "thermal-cooldown"]
# ★ agent 不能被远程停掉（否则客户端就失联了）
PROTECTED_SERVICES = {"zynq-agent"}

CHUNK_DEFAULT = 1 << 20     # 1 MB

# ★ 这些路径白名单是 Linux 板子的；在 Windows 上跑自检时要区别对待
IS_LINUX = (os.name == "posix")

# ★ agent 的安装目录。板上是 /home/zynq；测试时可以用环境变量指到别处，
#   否则 import agent.hw_change 会失败（Windows 上没有 /home/zynq）。
AGENT_DIR = os.environ.get("XIAOBAI_AGENT_DIR", "/home/zynq")


def conf():
    c = dict(DEFAULT_CONF)
    try:
        c.update(json.load(open(CONF_FILE, encoding="utf-8")))
    except Exception:
        pass
    return c


AUDIT_MAX_BYTES = 512 * 1024      # 审计日志超过 512KB 就轮转
AUDIT_KEEP = 3                    # 保留最近 3 个历史文件


def audit_rotate():
    """审计日志轮转

    ★ 为什么需要：审计是【只追加】的，跑久了会一直涨。
      板子 flash 有限，得有个上限。
      做法：audit.jsonl -> audit.jsonl.1 -> .2 -> .3，最老的删掉。

    ★ 只在超过阈值时做，而且失败也不能影响正常写审计。
    """
    try:
        if not os.path.exists(AUDIT_FILE):
            return False
        if os.path.getsize(AUDIT_FILE) < AUDIT_MAX_BYTES:
            return False
        # 老的一步步往后挪
        for i in range(AUDIT_KEEP - 1, 0, -1):
            src = "%s.%d" % (AUDIT_FILE, i)
            dst = "%s.%d" % (AUDIT_FILE, i + 1)
            if os.path.exists(src):
                try:
                    os.replace(src, dst)
                except Exception:
                    pass
        try:
            os.replace(AUDIT_FILE, AUDIT_FILE + ".1")
        except Exception:
            pass
        try:
            os.remove("%s.%d" % (AUDIT_FILE, AUDIT_KEEP + 1))
        except Exception:
            pass
        return True
    except Exception:
        return False


def audit(action, detail, ok=True, who="remote"):
    """所有写操作都记审计（★ 超过阈值会自动轮转）"""
    try:
        os.makedirs(os.path.dirname(AUDIT_FILE), exist_ok=True)
        # 每 200 条才查一次大小，别每次都 stat
        global _audit_n
        try:
            _audit_n += 1
        except NameError:
            _audit_n = 1
        if _audit_n % 200 == 0:
            audit_rotate()
        rec = {"ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "who": who, "action": action, "detail": str(detail)[:400],
               "ok": bool(ok)}
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------- 小工具
def sh(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, shell=isinstance(cmd, str),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=timeout)
        return p.returncode, (p.stdout or b"").decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return -1, "[超时 %ds]" % timeout
    except Exception as e:
        return -1, "%s: %s" % (type(e).__name__, e)


def pl_read(base, off, width=4):
    """★ fork 子进程读 —— 读空地址会 SIGBUS，不 fork 就把这个服务打死"""
    code = (
        "import mmap,os,struct,sys\n"
        "fd=os.open('/dev/mem', os.O_RDONLY|os.O_SYNC)\n"
        "m=mmap.mmap(fd, 4096, mmap.MAP_SHARED, mmap.PROT_READ, offset=%d)\n"
        "print(struct.unpack_from('<I', m, %d)[0])\n" % (base, off))
    rc, out = sh(["python3", "-c", code], 10)
    if rc != 0:
        return None
    try:
        return int(out.strip().split("\n")[-1])
    except Exception:
        return None


def pl_write(base, off, val):
    code = (
        "import mmap,os,struct,sys\n"
        "fd=os.open('/dev/mem', os.O_RDWR|os.O_SYNC)\n"
        "m=mmap.mmap(fd, 4096, mmap.MAP_SHARED,"
        " mmap.PROT_READ|mmap.PROT_WRITE, offset=%d)\n"
        "struct.pack_into('<I', m, %d, %d)\n" % (base, off, val & 0xFFFFFFFF))
    rc, out = sh(["python3", "-c", code], 10)
    return rc == 0


def read_temp():
    try:
        raw = int(open("/sys/bus/iio/devices/iio:device0/in_temp0_raw").read())
        sc = float(open("/sys/bus/iio/devices/iio:device0/in_temp0_scale").read())
        of = float(open("/sys/bus/iio/devices/iio:device0/in_temp0_offset").read())
        return round((raw + of) * sc / 1000.0, 1)
    except Exception:
        return None


def thermal_state():
    try:
        return json.load(open("/run/thermal/state.json", encoding="utf-8"))
    except Exception:
        return {}


def md5_of(path, limit=None):
    try:
        h = hashlib.md5()
        with open(path, "rb") as f:
            while True:
                c = f.read(1 << 20)
                if not c:
                    break
                h.update(c)
        return h.hexdigest()
    except Exception:
        return None


def svc_state(name):
    rc, out = sh(["systemctl", "is-active", name], 5)
    return out.strip() or "unknown"


# ---------------------------------------------------------------- 路径安全
def path_ok(path, write=False):
    """检查路径在白名单内，返回 (ok, 真实路径, 原因)

    ★★★ 关键设计：**用 posixpath 做规范化，不用 os.path**。
      为什么：这块板子是 Linux，白名单是 Linux 路径；
      但在 Windows 上跑自检时，os.path.realpath("/home/...") 会变成
      "D:\\home\\..."，Windows 的 os.path.isabs("/foo") 又是 False ——
      同一份逻辑两个平台结论不一样，自检就没意义了。

      所以：
        · 规范化/白名单判断一律用 posixpath（跨平台一致）
        · 只有在 Linux 上才额外做 realpath（解符号链接、防绕过）
        · Windows 上拿 posixpath 的结果当"真实路径"用
    """
    import posixpath

    p = (path or "").replace("\\", "/").strip()
    if not p.startswith("/"):
        return False, p, "必须是绝对路径（以 / 开头）"

    norm = posixpath.normpath(p)
    parts = norm.split("/")
    if ".." in parts:
        return False, norm, "路径里不允许 ..（防穿越）"

    allowed = False
    for root in ALLOW_ROOTS:
        if norm == root or norm.startswith(root.rstrip("/") + "/"):
            allowed = True
            break
    if not allowed:
        return False, norm, "路径不在白名单内（可访问：%s）" % ", ".join(ALLOW_ROOTS)

    if norm.startswith("/mnt/boot"):
        if not BOOT_ALLOW.match(norm):
            return False, norm, "/mnt/boot 下只允许操作 system.bit* 和 BOOT.BIN*"

    if write:
        for ro in READONLY_ROOTS:
            if norm == ro or norm.startswith(ro.rstrip("/") + "/"):
                return False, norm, "%s 是只读的" % ro

    # Linux 上再做一次 realpath，防止用符号链接绕过白名单
    if IS_LINUX:
        try:
            rp = os.path.realpath(p)
            ok2 = False
            for root in ALLOW_ROOTS:
                if rp == root or rp.startswith(root.rstrip("/") + "/"):
                    ok2 = True
                    break
            if not ok2:
                return False, rp, "符号链接指向白名单之外：%s" % rp
            if rp.startswith("/mnt/boot") and not BOOT_ALLOW.match(rp):
                return False, rp, "符号链接绕到了 /mnt/boot 之外"
            return True, rp, ""
        except Exception:
            return True, norm, ""
    return True, norm, ""


# ---------------------------------------------------------------- 业务处理
class Api(object):
    def __init__(self, cfg):
        self.cfg = cfg
        self.uploads = {}          # upload_id -> {...}
        self.lock = threading.Lock()
        os.makedirs(UPLOAD_DIR, exist_ok=True)

    # ---- ① 信息 ----
    def info(self):
        st = thermal_state()
        up = 0.0
        try:
            up = float(open("/proc/uptime").read().split()[0])
        except Exception:
            pass
        h = int(up // 3600)
        m = int((up % 3600) // 60)

        mac = ""
        ip = ""
        try:
            for nic in os.listdir("/sys/class/net"):
                if nic.startswith("wl"):
                    mac = open("/sys/class/net/%s/address" % nic).read().strip()
                    break
            rc, out = sh("hostname -I", 5)
            ip = out.strip().split()[0] if out.strip() else ""
        except Exception:
            pass

        bit = {}
        for p in ("/mnt/boot/system.bit",):
            if os.path.exists(p):
                bit = {"file": p, "size": os.path.getsize(p),
                       "mtime": datetime.datetime.fromtimestamp(
                           os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M:%S")}
                # ★ md5 读一次要 4MB，缓存起来（按 mtime）
                ck = "/run/xiaobai-bit.md5"
                try:
                    if os.path.exists(ck):
                        d = json.load(open(ck))
                        if d.get("mtime") == bit["mtime"]:
                            bit["md5"] = d.get("md5")
                except Exception:
                    pass
                if "md5" not in bit:
                    md5 = md5_of(p)
                    bit["md5"] = md5
                    try:
                        json.dump({"mtime": bit["mtime"], "md5": md5},
                                  open(ck, "w"))
                    except Exception:
                        pass

        tools_n = 0
        try:
            sys.path.insert(0, AGENT_DIR)
            from agent import tools as T
            # ★★★ 必须把 hw_tools 也 import 进来 —— 那 16 个 hw_* 工具
            #   是靠 @tool 装饰器在 import 时注册的，不 import 就数不到。
            #   （踩过：/info 里工具数一直显示 12，实际有 28）
            import agent.hw_tools  # noqa: F401
            tools_n = len(T.REGISTRY)
        except Exception:
            pass

        return {
            "ok": True,
            "hostname": socket.gethostname(),
            "ip": ip, "mac": mac,
            "model": "正点原子 领航者 ZYNQ7020 V3.9",
            "kernel": os.uname().release if hasattr(os, "uname") else "",
            "uptime_sec": int(up),
            "uptime_human": "%d 小时 %d 分" % (h, m),
            "temperature_c": read_temp(),
            "thermal_level": st.get("level", "?"),
            "services": {s: svc_state(s) for s in SERVICES},
            "bitstream": bit,
            "tools_count": tools_n,
            "silent_locked": os.path.exists("/etc/zynq-silent"),
        }

    # ---- ② 文件 ----
    def fs_list(self, path):
        ok, rp, why = path_ok(path)
        if not ok:
            return {"ok": False, "error": why}
        if not os.path.isdir(rp):
            return {"ok": False, "error": "不是目录: %s" % rp}
        items = []
        try:
            for n in sorted(os.listdir(rp)):
                fp = os.path.join(rp, n)
                try:
                    stt = os.stat(fp)
                    items.append({
                        "name": n,
                        "type": "dir" if os.path.isdir(fp) else "file",
                        "size": stt.st_size,
                        "mtime": datetime.datetime.fromtimestamp(
                            stt.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    })
                except OSError:
                    pass
        except Exception as e:
            return {"ok": False, "error": str(e)}
        du = shutil.disk_usage(rp)
        return {"ok": True, "path": rp, "items": items,
                "free_bytes": du.free, "total_bytes": du.total}

    def fs_stat(self, path):
        ok, rp, why = path_ok(path)
        if not ok:
            return {"ok": False, "error": why}
        if not os.path.exists(rp):
            return {"ok": False, "error": "不存在: %s" % rp}
        stt = os.stat(rp)
        return {"ok": True, "name": os.path.basename(rp), "path": rp,
                "size": stt.st_size, "md5": md5_of(rp),
                "mtime": datetime.datetime.fromtimestamp(
                    stt.st_mtime).strftime("%Y-%m-%d %H:%M:%S")}

    def fs_delete(self, path):
        if not self.cfg.get("enable_write", True):
            return {"ok": False, "error": "板子设为只读模式（enable_write=false）"}
        ok, rp, why = path_ok(path, write=True)
        if not ok:
            return {"ok": False, "error": why}
        if not os.path.exists(rp):
            return {"ok": False, "error": "不存在: %s" % rp}
        if os.path.isdir(rp):
            try:
                shutil.rmtree(rp)
            except Exception as e:
                return {"ok": False, "error": str(e)}
        else:
            try:
                os.remove(rp)
            except Exception as e:
                return {"ok": False, "error": str(e)}
        audit("fs_delete", rp)
        return {"ok": True, "deleted": rp}

    def fs_mkdir(self, path):
        if not self.cfg.get("enable_write", True):
            return {"ok": False, "error": "板子设为只读模式"}
        ok, rp, why = path_ok(path, write=True)
        if not ok:
            return {"ok": False, "error": why}
        try:
            os.makedirs(rp, exist_ok=True)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        audit("fs_mkdir", rp)
        return {"ok": True, "path": rp}

    def upload_begin(self, path, size, md5=None):
        if not self.cfg.get("enable_write", True):
            return {"ok": False, "error": "板子设为只读模式"}
        ok, rp, why = path_ok(path, write=True)
        if not ok:
            return {"ok": False, "error": why}
        uid = "up_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + \
              "_%03d" % (int(time.time() * 997) % 1000)
        tmp = os.path.join(UPLOAD_DIR, uid)
        with self.lock:
            self.uploads[uid] = {"path": rp, "tmp": tmp, "size": int(size or 0),
                                 "md5": (md5 or "").lower(), "received": 0}
        open(tmp, "wb").close()
        audit("upload_begin", "%s (%s 字节)" % (rp, size))
        return {"ok": True, "upload_id": uid, "chunk_size": CHUNK_DEFAULT}

    def upload_chunk(self, uid, offset, data_b64):
        if not self.cfg.get("enable_write", True):
            return {"ok": False, "error": "板子设为只读模式"}
        with self.lock:
            u = self.uploads.get(uid)
        if not u:
            return {"ok": False, "error": "没有这个 upload_id（是不是服务重启了？）"}
        try:
            data = base64.b64decode(data_b64)
        except Exception as e:
            return {"ok": False, "error": "base64 解码失败: %s" % e}
        try:
            # ★ 用 r+b 随机写，支持乱序/续传
            with open(u["tmp"], "r+b") as f:
                f.seek(int(offset))
                f.write(data)
            with self.lock:
                u["received"] = max(u["received"], int(offset) + len(data))
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "received": u["received"], "total": u["size"]}

    def upload_status(self, uid):
        with self.lock:
            u = self.uploads.get(uid)
        if not u:
            return {"ok": False, "error": "没有这个 upload_id"}
        return {"ok": True, "received": u["received"], "total": u["size"]}

    def upload_end(self, uid):
        with self.lock:
            u = self.uploads.pop(uid, None)
        if not u:
            return {"ok": False, "error": "没有这个 upload_id"}
        got_size = os.path.getsize(u["tmp"])
        if u["size"] and got_size != u["size"]:
            return {"ok": False,
                    "error": "大小不符：收到 %d，期望 %d" % (got_size, u["size"]),
                    "code": "size_mismatch"}
        got_md5 = md5_of(u["tmp"])
        if u["md5"] and got_md5 != u["md5"]:
            return {"ok": False, "error": "md5 不符，文件可能传坏了",
                    "code": "md5_mismatch",
                    "expect": u["md5"], "got": got_md5}
        try:
            os.makedirs(os.path.dirname(u["path"]), exist_ok=True)
            shutil.move(u["tmp"], u["path"])
        except Exception as e:
            return {"ok": False, "error": "落盘失败: %s" % e}
        audit("upload_end", "%s (%d 字节, md5 %s)" % (u["path"], got_size, got_md5))
        return {"ok": True, "path": u["path"], "size": got_size, "md5": got_md5}

    # ---- ③ 硬件 ----
    def hw_regs(self, base_s, off_s, count=1):
        base = PL_MAP.get(base_s)
        if base is None:
            try:
                base = int(str(base_s), 0)
            except Exception:
                return {"ok": False,
                        "error": "base 要给已知名字（%s）或十六进制地址"
                                 % ", ".join(sorted(PL_MAP))}
        try:
            off0 = int(str(off_s or "0"), 0)
        except Exception:
            return {"ok": False, "error": "offset 要像 0x34 这样"}
        n = max(1, min(int(count or 1), 64))
        regs = []
        for i in range(n):
            o = off0 + i * 4
            v = pl_read(base, o)
            if v is None:
                return {"ok": False,
                        "error": "读不到 0x%08X+0x%02X（这个地址在 PL 里没映射）"
                                 % (base, o),
                        "regs": regs}
            regs.append({"offset": "0x%02X" % o, "value": "0x%08X" % v})
        return {"ok": True, "base": "0x%08X" % base, "regs": regs}

    def hw_reg_write(self, base_s, off_s, val_s):
        if not self.cfg.get("enable_write", True):
            return {"ok": False, "error": "板子设为只读模式"}
        base = PL_MAP.get(base_s)
        if base is None:
            try:
                base = int(str(base_s), 0)
            except Exception:
                return {"ok": False, "error": "base 不认识"}
        try:
            off = int(str(off_s), 0)
            val = int(str(val_s), 0)
        except Exception:
            return {"ok": False, "error": "offset/value 要是数字"}
        old = pl_read(base, off)
        if old is None:
            return {"ok": False, "error": "这个地址读不了，拒绝写（可能没映射）"}
        if not pl_write(base, off, val):
            return {"ok": False, "error": "写失败"}
        new = pl_read(base, off)
        audit("hw_reg_write", "0x%08X+0x%02X: 0x%X -> 0x%X" % (base, off, old, val))
        return {"ok": True, "old": "0x%08X" % old,
                "new": "0x%08X" % (new if new is not None else -1)}

    def hw_thermal(self, limit=60):
        st = thermal_state()
        hist = []
        try:
            for ln in open("/run/thermal/history.txt").read().splitlines()[-limit:]:
                p = ln.split()
                if len(p) >= 3:
                    hist.append({"t": p[0], "temp": float(p[1]), "level": p[2]})
        except Exception:
            pass
        return {"ok": True, "temp_c": read_temp(),
                "peak_c": st.get("peak"), "level": st.get("level", "?"),
                "thresholds": st.get("thresholds", {}),
                "stopped_services": st.get("stopped", []),
                "history": hist}

    def hw_services(self):
        return {"ok": True,
                "services": {s: svc_state(s) for s in SERVICES}}

    def hw_service(self, name, action):
        if not self.cfg.get("enable_write", True):
            return {"ok": False, "error": "板子设为只读模式"}
        if name not in SERVICES:
            return {"ok": False, "error": "不认识的服务 %s（可选：%s）"
                                          % (name, ", ".join(SERVICES))}
        if name in PROTECTED_SERVICES and action in ("stop", "restart"):
            return {"ok": False,
                    "error": "%s 不能远程 %s —— 停了客户端就失联了"
                             % (name, action)}
        if action not in ("start", "stop", "restart"):
            return {"ok": False, "error": "action 只能是 start/stop/restart"}
        rc, out = sh(["systemctl", action, name], 30)
        now = svc_state(name)
        audit("hw_service", "%s %s -> %s" % (action, name, now), rc == 0)
        return {"ok": rc == 0, "name": name, "action": action, "now": now,
                "error": "" if rc == 0 else out[:200]}

    def hw_logs(self, name, lines=100):
        n = max(1, min(int(lines or 100), 2000))
        if name in LOGS:
            p = LOGS[name]
            if not os.path.exists(p):
                return {"ok": False, "error": "日志不存在: %s" % p}
            rc, out = sh(["tail", "-n", str(n), p], 15)
            return {"ok": True, "name": name, "lines": out.split("\n")}
        if name == "agent":
            rc, out = sh(["journalctl", "-u", "zynq-agent", "-n", str(n),
                          "--no-pager"], 20)
            return {"ok": True, "name": name, "lines": out.split("\n")}
        if name == "system":
            rc, out = sh(["dmesg"], 15)
            return {"ok": True, "name": name,
                    "lines": out.split("\n")[-n:]}
        return {"ok": False, "error": "日志名可选：%s, agent, system"
                                      % ", ".join(LOGS)}

    # ---- ④ 变更历史 ----
    def _changes(self):
        try:
            sys.path.insert(0, AGENT_DIR)
            from agent import hw_change as HC
            return HC
        except Exception:
            return None

    def hw_changes(self, limit=50):
        HC = self._changes()
        if HC is None:
            return {"ok": False, "error": "加载 hw_change 失败"}
        recs = HC.change_list(max(1, min(int(limit or 50), 500)))
        out = []
        for r in reversed(recs):        # 新的在前
            has_snap = False
            try:
                has_snap = os.path.exists(os.path.join(
                    HC.SNAPSHOT_DIR, r.get("id", ""), "manifest.json"))
            except Exception:
                pass
            # ★★★ 旧记录的兼容处理（实测发现的）：
            #   早期版本的 _add_change 写记录时【没有 id 字段】，
            #   直接返回 id=None 会让客户端拿到一堆 null，
            #   而且 filters/rollback 都没法按 id 操作。
            #   ⇒ 给这类旧记录补一个合成 id（形如 legacy_3），
            #     并且明确标 rollbackable=false（它们确实没备份）。
            cid = r.get("id")
            if not cid:
                cid = "legacy_%d" % (len(out) + 1)
                legacy = True
            else:
                legacy = False
            # ★★★ rollbackable 不能只看字段【非空】，还要看文件【真的在】。
            #   踩过：变更单里记着 backup 路径，但那个备份早被清理了，
            #   客户端于是显示一个"点了必然失败"的回滚按钮。
            bak = r.get("backup")
            path = r.get("path")
            bak_alive = bool(bak and os.path.exists(bak))
            out.append({
                "id": cid,
                "ts": r.get("ts"),
                "kind": (r.get("kind") or "unknown"),
                "detail": (r.get("detail") or "（旧记录，没写明细）"),
                "result": (r.get("result") or ""),
                "who": r.get("who") or "?",
                "backup": bak, "path": path,
                "backup_exists": bak_alive,
                "has_snapshot": has_snap,
                "legacy": legacy,          # ★ 客户端可以据此不显示回滚按钮
                "rollbackable": bool(not legacy and
                                     (has_snap or (bak_alive and path))),
            })
        return {"ok": True, "count": len(out), "changes": out}

    def hw_change_detail(self, cid):
        HC = self._changes()
        if HC is None:
            return {"ok": False, "error": "加载 hw_change 失败"}
        for r in HC.change_list(10000):
            if r.get("id") == cid:
                man = []
                try:
                    p = os.path.join(HC.SNAPSHOT_DIR, cid, "manifest.json")
                    if os.path.exists(p):
                        man = json.load(open(p, encoding="utf-8"))
                except Exception:
                    pass
                return {"ok": True, "change": r, "snapshot_manifest": man}
        return {"ok": False, "error": "没有这个变更单: %s" % cid}

    def hw_rollback(self, cid):
        if not self.cfg.get("enable_write", True):
            return {"ok": False, "error": "板子设为只读模式"}
        HC = self._changes()
        if HC is None:
            return {"ok": False, "error": "加载 hw_change 失败"}
        ok, why = HC.rollback(cid, verbose=False)
        audit("hw_rollback", "%s -> %s" % (cid, why), ok)
        return {"ok": ok, "id": cid, "detail": why,
                "error": "" if ok else why}

    # ---- ④b 转发给 agent（工具列表 / 直接调工具）----
    #
    # ★ 为什么要有这一层：
    #   客户端只需要连一个端口（8768），不用知道 agent 在 8765。
    #   而且这样以后 agent 换端口/换实现，客户端不用改。
    AGENT_URL = "http://127.0.0.1:8765"

    def agent_get(self, path, timeout=15):
        """GET 转发给 agent"""
        try:
            req = urllib.request.Request(self.AGENT_URL + path)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read().decode("utf-8", "replace")
            d = json.loads(b)
            if isinstance(d, dict):
                d.setdefault("ok", True)
                return d
            return {"ok": True, "result": d}
        except Exception as e:
            return {"ok": False,
                    "error": "转发给 agent 失败：%s: %s（zynq-agent 在跑吗？）"
                             % (type(e).__name__, e)}

    def agent_post(self, path, payload, timeout=25, audit_tag=None):
        """★ 通用 POST 转发给 agent（2026-10-03 新增）

        ★★★ 为什么需要（用户报的最后一个 bug）
        ────────────────────────────────────────────────────────────
        PC 客户端（xb_client.py）的 DEFAULT_PORT 是 8768，也就是【云端网关】。
        它保存设置时会调：
            POST /llm/settings  {"api_key": "..."}
            POST /llm/model     {"model": "..."}
        但这两个接口【只存在于 agent（8765）】，网关这边没有
        ⇒ 客户端拿到 {"ok": false, "error": "未知接口: /llm/settings"}
        ⇒ 「云端配置 API Key / 模型」全部静默失败（用户："能不能真的能配置"）。

        修法：照已有 /tools /tool 的做法，在网关上转发给 agent。
        客户端只连一个端口，agent 换实现也不用改客户端。
        ────────────────────────────────────────────────────────────
        """
        try:
            body = json.dumps(payload or {}).encode()
            req = urllib.request.Request(
                self.AGENT_URL + path, data=body,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read().decode("utf-8", "replace")
            d = json.loads(b)
            if isinstance(d, dict):
                d.setdefault("ok", True)
                if audit_tag:
                    audit(audit_tag, json.dumps(payload or {},
                                                ensure_ascii=False)[:140])
                return d
            return {"ok": True, "result": d}
        except Exception as e:
            return {"ok": False,
                    "error": "转发给 agent 失败：%s: %s" % (type(e).__name__, e)}

    def agent_tool(self, name, args, timeout=120):
        """POST /tool 转发给 agent"""
        if not name:
            return {"ok": False, "error": "要给 name（工具名）"}
        try:
            body = json.dumps({"name": name, "args": args or {}}).encode()
            req = urllib.request.Request(
                self.AGENT_URL + "/tool", data=body,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read().decode("utf-8", "replace")
            d = json.loads(b)
            if isinstance(d, dict):
                d.setdefault("ok", True)
                audit("tool", "%s %s" % (name, json.dumps(args or {},
                                                          ensure_ascii=False)[:120]))
                return d
            return {"ok": True, "result": d}
        except Exception as e:
            return {"ok": False,
                    "error": "转发给 agent 失败：%s: %s" % (type(e).__name__, e)}

    def agent_voice(self, text, timeout=120):
        """POST /voice 转发给 agent"""
        if not text:
            return {"ok": False, "error": "要给 text"}
        try:
            body = json.dumps({"text": text}).encode()
            req = urllib.request.Request(
                self.AGENT_URL + "/voice", data=body,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read().decode("utf-8", "replace")
            d = json.loads(b)
            if isinstance(d, dict):
                d.setdefault("ok", True)
                return d
            return {"ok": True, "reply": str(d)}
        except Exception as e:
            return {"ok": False,
                    "error": "转发给 agent 失败：%s: %s" % (type(e).__name__, e)}

    # ---- ④b ★ 云端推理契约（AI 负责人任务 G/H 的板端实现）----
    def infer(self, body, timeout=120):
        """POST /infer —— 按 AI 负责人 `02_文档/04_云端推理API与降级.md` 的契约

        ★ 为什么在板子上实现而不是调他的 serve/：
          他的 `model_backend.py` 是【纯 numpy 整数前向】，板子上没有 numpy；
          而我们板子上有【真的 PL 加速器】。
          ⇒ 按同一个契约实现，但推理走 PL：更快，而且演示的是真机。

        契约：
            { "type": "waveform"|"chat", "data": [...], "hint": "...", "api_key": "..." }
            → { "ok": true, "label": "...", "confidence": 0.93,
                "detail": {...}, "elapsed_ms": 240, "offline_mode": false }
        """
        try:
            import infer_local
        except Exception as e:
            return {"ok": False,
                    "error": "板端推理模块加载失败：%s: %s" % (type(e).__name__, e)}

        def _chat(text):
            r = self.agent_voice(text, timeout=timeout)
            if isinstance(r, dict):
                return r.get("reply") or r.get("error") or ""
            return str(r)

        try:
            return infer_local.infer(body, cloud_chat_fn=_chat)
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}

    def infer_health(self):
        """GET /infer/health"""
        try:
            import infer_local
            return infer_local.health()
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}

    # ---- ⑤ 对话 ----
    def _sessions(self):
        """拿到会话存储

        ★★★ 2026-10-03 换成 SharedStore（用户报"对话和板子不一致"）★★★
        之前这里返回 agent.storage.Store，它读写
        /var/lib/xiaobai/sessions/ —— 那个目录【一直是空的】，
        而板载 UI 的对话存在 /home/zynq/.agent_chats.json。
        ⇒ 客户端拉 /chat/sessions 永远拿到空列表，看着就是"没同步"。

        现在返回 SharedStore（agent/shared_chat.py）：
          · 接口和 Store 一模一样（cloud_api 这边一行都不用改）
          · 数据落在板载 UI 那个共享文件里
          · agent 的 /voice 也会往同一个文件追加
        ⇒ 板载 UI 和 PC 客户端看到的是同一份对话。
        """
        try:
            sys.path.insert(0, AGENT_DIR)
            from agent import shared_chat as SC
            return SC.SharedStore()
        except Exception:
            # 兜底：退回原来的 Store（至少不 500）
            try:
                sys.path.insert(0, AGENT_DIR)
                from agent import sessions as SS
                return SS.Store(verbose=False)
            except Exception:
                return None

    def chat(self, text, session_id=None):
        try:
            sys.path.insert(0, AGENT_DIR)
            from agent.core import Agent, Session
            st = self._sessions()

            sid = session_id
            if st is not None:
                if not sid:
                    sid = st.new(text)
                # ★ 把历史喂回去 —— 这样多轮对话记得住
                hist = st.history(sid)
            else:
                hist = []
                if not sid:
                    sid = "s_%d" % int(time.time())

            sess = Session()
            # 把已有历史装进 Session（core.Session 有 add）
            for m in hist:
                try:
                    sess.add({"role": m.get("role"),
                              "content": m.get("content") or ""})
                except Exception:
                    pass

            # ★ CHAT_API_FIX_V1：修复 /chat 报
            #   TypeError: int() argument must be ... not 'Session'
            #
            # 根因：Agent.run(task, max_rounds=None, system=None, use_tools=True)
            #   第 2 个参数是 max_rounds，不是 session！
            #   而旧代码写的 ag.run(text, sess) ⇒ sess 被当 max_rounds
            #   ⇒ mr = int(sess) ⇒ TypeError
            #
            # 正确用法：Agent(session=sess).run(text)
            #   Agent.__init__ 里有 self.session = session or Session(...)
            #
            # 另：Agent 根本没有 ask() 方法，所以 hasattr(ag,"ask") 永远为假
            #   ⇒ 一定走到 run(text, sess) 这个错误分支
            ag = Agent(session=sess)
            _r = ag.run(text)
            # run() 返回 (reply, meta) 元组，也可能只返回 reply
            if isinstance(_r, tuple):
                reply = _r[0]
            else:
                reply = _r

            if st is not None:
                st.append(sid, "user", text)
                st.append(sid, "assistant", str(reply))
                turns = st.turns(sid)
            else:
                turns = 1

            return {"ok": True, "session_id": sid, "reply": str(reply)[:4000],
                    "rounds": turns}
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}

    def chat_sessions(self, limit=40, include_archived=False):
        st = self._sessions()
        if st is None:
            return {"ok": False, "error": "会话模块加载失败"}
        # ★ 归档过滤交给 shared_chat 那层（它知道 archived 字段在哪）
        try:
            from agent import shared_chat as _sc
            ss = _sc.list_sessions(limit, include_archived=include_archived)
            return {"ok": True, "sessions": ss, "stats": st.stats()}
        except Exception:
            return {"ok": True, "sessions": st.list(limit),
                    "stats": st.stats()}

    def chat_archive(self, session_id, on=True):
        """★ 归档 / 取消归档（2026-10-03 用户要的"归档隐藏，两边同步"）

        归档的会话不在默认列表里显示，但数据还在 —— 想找回来
        include_archived=1 就能看到，也能取消归档。
        """
        if not session_id:
            return {"ok": False, "error": "要给 session_id"}
        try:
            from agent import shared_chat as _sc
            ok, title = _sc.archive(session_id, on)
            if ok:
                audit("chat_archive", "%s -> %s"
                      % ("归档" if on else "取消归档", session_id))
            return {"ok": ok, "id": session_id, "archived": bool(on),
                    "title": title,
                    "error": "" if ok else "没找到这个会话"}
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}

    def chat_clear(self, session_id=None):
        st = self._sessions()
        if st is None:
            return {"ok": False, "error": "会话模块加载失败"}
        if session_id:
            return {"ok": True, "deleted": st.delete(session_id)}
        return {"ok": True, "deleted": st.clear_all()}

    def chat_history(self, session_id):
        """拿某个会话的完整历史（客户端"打开历史对话"用）"""
        st = self._sessions()
        if st is None:
            return {"ok": False, "error": "会话模块加载失败"}
        h = st.history(session_id)
        if not h:
            return {"ok": False, "error": "没有这个会话或它是空的"}
        return {"ok": True, "session_id": session_id, "messages": h,
                "turns": st.turns(session_id)}

    def chat_export(self, session_id):
        """导出成 markdown（留档 / 给评审看）"""
        st = self._sessions()
        if st is None:
            return {"ok": False, "error": "会话模块加载失败"}
        md = st.export(session_id, "md")
        if md is None:
            return {"ok": False, "error": "没有这个会话"}
        return {"ok": True, "session_id": session_id, "markdown": md}

    def llm_config(self, mode=None):
        """读/改推理模式（local / cloud / auto）

        ★★★ 这里原来是个【假接口】（2026-10-02 修）★★★
        旧代码是：
            cur = env.get("AGENT_MODE", "cloud")
            if mode:
                audit("llm_config", "mode -> %s" % mode)
                cur = mode                     # ← 只改了个局部变量
            return {"ok": True, "mode": cur, ...}

        ⇒ 调用方拿到 {"ok": true, "mode": "local"}，以为切过去了，
          实际上【什么都没发生】：既没落盘，也没通知运行中的 agent。
          这比直接报错还坏 —— 是"假成功"。

        ⇒ 现在改成：写 /home/zynq/.agent_mode，agent 那边的 Tiers.mode
          是动态属性（1 秒缓存），所以【立刻生效，不用重启】。
        """
        env = {}
        try:
            for ln in open("/etc/zynq-agent.env", encoding="utf-8").read().splitlines():
                if "=" in ln and not ln.strip().startswith("#"):
                    k, v = ln.split("=", 1)
                    env[k.strip()] = v.strip()
        except Exception:
            pass

        # ★ 模式文件的读写（和 agent/tiers.py 里的常量保持一致）
        mode_file = "/home/zynq/.agent_mode"

        def _read_mode():
            try:
                with open(mode_file, encoding="utf-8") as f:
                    m = f.read().strip().lower()
                if m in ("local", "cloud", "auto"):
                    return m
            except Exception:
                pass
            m = env.get("AGENT_MODE", "auto")
            return m if m in ("local", "cloud", "auto") else "auto"

        def _write_mode(m):
            try:
                tmp = mode_file + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(m + "\n")
                os.replace(tmp, mode_file)
                try:
                    os.chmod(mode_file, 0o644)
                except Exception:
                    pass
                return True
            except Exception:
                return False

        cur = _read_mode()
        if mode:
            if mode not in ("local", "cloud", "auto"):
                return {"ok": False, "error": "mode 只能是 local/cloud/auto"}
            if not _write_mode(mode):
                return {"ok": False,
                        "error": "写不了 %s（权限？）" % mode_file}
            audit("llm_config", "mode -> %s（已落盘 %s）" % (mode, mode_file))
            cur = mode
        # ★★★ 算出【真正生效】的模型（2026-10-03 修）★★★
        #   踩过：客户端设置页显示 model=deepseek-chat，板子实际用
        #   deepseek-flash —— 两边不一致，用户看到就懵
        #   （用户原话："模型不能用板子的吗？为什么要自己配"）。
        #   根因：这里原来只读 /etc/zynq-agent.env 的 AGENT_MODEL，
        #         而 agent 的真实优先级是：
        #           覆盖文件(.agent_settings.json) > 环境变量 > .agent.json > 默认
        #         "客户端切模型"写的是【覆盖文件】，它优先级最高。
        #   ⇒ 这里必须按同样的优先级算，不能只看环境变量。
        _model = env.get("AGENT_MODEL", "deepseek-chat")
        _has_key = bool(env.get("DEEPSEEK_API_KEY"))
        try:
            import json as _json
            _ov = _json.load(open("/home/zynq/.agent_settings.json",
                                  encoding="utf-8"))
            if isinstance(_ov, dict):
                if _ov.get("model"):
                    _model = str(_ov["model"])
                # api_key：覆盖文件里【有值】才算数；
                # 没有这个键或为空 -> 回落环境变量（上面已经算过）
                if _ov.get("api_key"):
                    _has_key = True
        except Exception:
            pass
        return {"ok": True, "mode": cur,
                "mode_file": mode_file,
                "effect": "立刻生效（agent 每次读文件，不用重启）",
                "model": _model,
                "has_key": _has_key,
                "cloud_reachable": True}

    # ---- ⑤b API key 写入 ----
    def llm_set_key(self, key, provider="deepseek"):
        """设置云端 API key

        ★★★ 三条安全规矩：
          ① key 写完【不回显】—— 只返回 has_key
          ② 落盘文件权限设成 600（只有 root/zynq 能读）
          ③ 记审计，但审计里【只记 key 的前 4 位 + 长度】，不记全文
             （审计日志是给客户端看的，不能把 key 泄进去）

        ★ 写的是 /etc/zynq-agent.env（agent 启动时读它）。
          改完要重启 zynq-agent 才生效。
        """
        if not self.cfg.get("enable_write", True):
            return {"ok": False, "error": "板子设为只读模式"}
        key = (key or "").strip()
        if not key:
            return {"ok": False, "error": "要给 key"}
        if len(key) < 16:
            return {"ok": False, "error": "key 太短了，不像是真的"}
        # ★ 只允许 ASCII（HTTP 头和 shell 里都安全）
        try:
            key.encode("ascii")
        except Exception:
            return {"ok": False, "error": "key 必须是 ASCII 字符"}
        if any(c in key for c in "\"'`$\\\n\r ;&|"):
            return {"ok": False, "error": "key 里有可疑字符，拒绝"}

        envf = "/etc/zynq-agent.env"
        var = "DEEPSEEK_API_KEY" if provider == "deepseek" else \
              ("%s_API_KEY" % provider.upper())
        try:
            lines = []
            if os.path.exists(envf):
                with open(envf, encoding="utf-8") as f:
                    lines = f.read().splitlines()
            # 换掉已有那行，没有就追加
            hit = False
            for i, ln in enumerate(lines):
                if ln.strip().startswith(var + "="):
                    lines[i] = "%s=%s" % (var, key)
                    hit = True
                    break
            if not hit:
                lines.append("%s=%s" % (var, key))
            tmp = envf + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            os.chmod(tmp, 0o600)
            os.replace(tmp, envf)
            os.chmod(envf, 0o600)
        except Exception as e:
            return {"ok": False, "error": "写 %s 失败: %s" % (envf, e)}

        # ★ 审计里绝不写全 key
        audit("llm_key", "%s 已更新（%s…，共 %d 字符）"
              % (var, key[:4], len(key)))
        return {"ok": True, "provider": provider, "has_key": True,
                "hint": key[:4] + "…",
                "need_restart": "zynq-agent",
                "note": "重启 zynq-agent 后生效"}

    def llm_restart_agent(self):
        """改完 key 重启 agent（key 是启动时读的）"""
        if not self.cfg.get("enable_write", True):
            return {"ok": False, "error": "板子设为只读模式"}
        rc, out = sh(["systemctl", "restart", "zynq-agent"], 30)
        time.sleep(3)
        st = svc_state("zynq-agent")
        audit("llm_key", "重启 zynq-agent -> %s" % st, rc == 0)
        return {"ok": rc == 0, "now": st,
                "error": "" if rc == 0 else out[:200]}

    # ---- ⑥ 构建 ----
    def fpga_build(self, preset, desc, steps, artifacts, timeout_sec, wait=False):
        if not self.cfg.get("enable_write", True):
            return {"ok": False, "error": "板子设为只读模式"}
        try:
            sys.path.insert(0, AGENT_DIR)
            from agent import tools as T
            import agent.hw_tools  # noqa: F401  确保注册
            r = T.call("hw_fpga_build", {
                "preset": preset, "desc": desc, "steps": steps or [],
                "artifacts": artifacts or [],
                "timeout_sec": timeout_sec or 3600, "wait": bool(wait),
            }, {})
            jid = ""
            m = re.search(r"任务号：(\S+)", r)
            if m:
                jid = m.group(1)
            audit("fpga_build", "%s %s" % (preset, desc))
            return {"ok": True, "id": jid, "status": "pending", "detail": r[:2000]}
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}

    def fpga_build_get(self, jid):
        d = "/home/zynq/fpga_jobs"
        for suf in (".result.json", ".request.json"):
            p = os.path.join(d, jid + suf)
            if os.path.exists(p):
                try:
                    obj = json.load(open(p, encoding="utf-8"))
                    obj["ok"] = True
                    if suf == ".request.json":
                        obj["status"] = "pending"
                    return obj
                except Exception as e:
                    return {"ok": False, "error": str(e)}
        return {"ok": False, "error": "没有这个构建任务: %s" % jid}

    def fpga_builds(self, limit=20):
        d = "/home/zynq/fpga_jobs"
        if not os.path.isdir(d):
            return {"ok": True, "builds": []}
        ids = sorted(set(os.path.basename(f).split(".")[0]
                         for f in os.listdir(d) if ".request.json" in f or
                         ".result.json" in f))
        out = []
        for j in ids[-max(1, min(int(limit or 20), 200)):]:
            rp = os.path.join(d, j + ".result.json")
            st = "pending"
            ds = ""
            if os.path.exists(rp):
                try:
                    o = json.load(open(rp, encoding="utf-8"))
                    st = o.get("status", "?")
                except Exception:
                    st = "坏"
            qp = os.path.join(d, j + ".request.json")
            if os.path.exists(qp):
                try:
                    ds = json.load(open(qp, encoding="utf-8")).get("desc", "")
                except Exception:
                    pass
            out.append({"id": j, "status": st, "desc": ds})
        return {"ok": True, "builds": list(reversed(out))}


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    api = None
    cfg = None

    def log_message(self, *a):
        pass          # 别刷屏

    # ---- 响应助手 ----
    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, ctype="application/octet-stream",
                   offset=0, length=None):
        total = os.path.getsize(path)
        if length is None:
            length = total - offset
        self.send_response(200 if offset == 0 else 206)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Content-Disposition",
                         'attachment; filename="%s"' % os.path.basename(path))
        self.send_header("Access-Control-Allow-Origin", "*")
        if offset:
            self.send_header("Content-Range",
                             "bytes %d-%d/%d" % (offset, offset + length - 1, total))
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(offset)
            left = length
            while left > 0:
                c = f.read(min(1 << 20, left))
                if not c:
                    break
                self.wfile.write(c)
                left -= len(c)

    # ---- 鉴权 ----
    def _authed(self, q):
        if self.path.split("?")[0] in ("/health",):
            return True
        tok = ""
        a = self.headers.get("Authorization", "")
        if a.startswith("Bearer "):
            tok = a[7:].strip()
        if not tok:
            tok = (q.get("token") or [""])[0]
        return tok and tok == self.cfg.get("token")

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length", "0") or 0)
        except Exception:
            n = 0
        if n <= 0:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _parse(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        return u.path, q

    def _one(self, q, k, d=""):
        v = q.get(k)
        return v[0] if v else d

    # ---- GET ----
    def do_GET(self):
        path, q = self._parse()
        if path == "/health":
            return self._send_json({"ok": True, "name": "系统管家小白",
                                    "version": "1.0",
                                    "port": self.cfg.get("port", 8768)})
        if not self._authed(q):
            return self._send_json({"ok": False, "error": "unauthorized",
                                    "code": "unauthorized"}, 401)
        try:
            if path == "/info":
                return self._send_json(self.api.info())
            # ★ AI 负责人任务 G 契约里的 GET /health（推理服务健康）
            if path == "/infer/health":
                return self._send_json(self.api.infer_health())
            if path == "/fs/list":
                return self._send_json(self.api.fs_list(self._one(q, "path", "/home/zynq")))
            if path == "/fs/stat":
                return self._send_json(self.api.fs_stat(self._one(q, "path")))
            if path == "/fs/download":
                ok, rp, why = path_ok(self._one(q, "path"))
                if not ok:
                    return self._send_json({"ok": False, "error": why}, 403)
                if not os.path.isfile(rp):
                    return self._send_json({"ok": False, "error": "不是文件"}, 404)
                # Range 支持
                rng = self.headers.get("Range", "")
                off = 0
                m = re.match(r"bytes=(\d+)-", rng or "")
                if m:
                    off = int(m.group(1))
                return self._send_file(rp, offset=off)
            if path == "/fs/upload/status":
                return self._send_json(self.api.upload_status(self._one(q, "upload_id")))
            if path == "/hw/regs":
                return self._send_json(self.api.hw_regs(
                    self._one(q, "base"), self._one(q, "offset", "0"),
                    self._one(q, "count", "1")))
            if path == "/hw/thermal":
                return self._send_json(self.api.hw_thermal(
                    int(self._one(q, "limit", "60") or 60)))
            if path == "/hw/services":
                return self._send_json(self.api.hw_services())
            if path == "/hw/logs":
                return self._send_json(self.api.hw_logs(
                    self._one(q, "name", "desktop"),
                    int(self._one(q, "lines", "100") or 100)))
            if path == "/hw/changes":
                return self._send_json(self.api.hw_changes(
                    int(self._one(q, "limit", "50") or 50)))
            if path.startswith("/hw/changes/"):
                return self._send_json(self.api.hw_change_detail(
                    path[len("/hw/changes/"):]))
            # ★★★ 工具列表 —— 转发给 agent（8765）
            #
            # 踩过：接口文档里写了"转发给 agent（/tools /tool 之类）"，
            # 但代码里只留了句注释，从来没实现 —— 客户端调 /tools
            # 拿到的是 "未知接口: /tools"。
            # 现在真转发。
            if path == "/tools":
                return self._send_json(self.api.agent_get("/tools"))
            if path == "/voice":
                # GET 不常见，但也允许（返回 agent 的说明）
                return self._send_json(self.api.agent_get("/health"))
            if path == "/chat/sessions":
                # ★ include_archived=1 时把归档的也列出来（带 archived 标记）
                return self._send_json(self.api.chat_sessions(
                    int(self._one(q, "limit", "40") or 40),
                    include_archived=(str(self._one(q, "include_archived",
                                                     "")) in ("1", "true",
                                                              "yes"))))
            # ★ 新增：打开某个历史会话 / 导出成 markdown
            if path.startswith("/chat/history/"):
                return self._send_json(self.api.chat_history(
                    path[len("/chat/history/"):]))
            if path.startswith("/chat/export/"):
                return self._send_json(self.api.chat_export(
                    path[len("/chat/export/"):]))
            if path == "/llm/config":
                return self._send_json(self.api.llm_config())
            # ★★★ GET /llm/models 转发给 agent（2026-10-03 补）
            #   PC 客户端设置页有个「从板子拉模型列表」按钮，
            #   它 GET 的也是 8768（DEFAULT_PORT）⇒ 之前同样拿不到。
            if path in ("/llm/models", "/models"):
                return self._send_json(self.api.agent_get(path, timeout=30))
            # ★ GET /llm/settings 转发（客户端"打开设置"时回显当前配置）
            if path == "/llm/settings":
                return self._send_json(self.api.agent_get(path, timeout=15))
            if path == "/fpga/builds":
                return self._send_json(self.api.fpga_builds(
                    int(self._one(q, "limit", "20") or 20)))
            if path.startswith("/fpga/build/"):
                return self._send_json(self.api.fpga_build_get(
                    path[len("/fpga/build/"):]))
            # 转发给 agent（/tools /tool 之类）
            return self._send_json({"ok": False, "error": "未知接口: %s" % path}, 404)
        except Exception as e:
            import traceback
            return self._send_json({"ok": False,
                                    "error": "%s: %s" % (type(e).__name__, e),
                                    "trace": traceback.format_exc()[-500:]}, 500)

    # ---- POST ----
    def do_POST(self):
        path, q = self._parse()
        # ★★ /infer 的认证放在 body 里（AI 负责人的契约就是这么定的）：
        #      { "type":..., "data":..., "api_key": "<token>" }
        #    所以这个端点【先读 body 再认证】——
        #    Bearer 头对得上、或者 body 里的 api_key 对得上，都放行。
        #    （这样他的 demo_offline.py / client.py 不用改就能直接连）
        if path == "/infer":
            a = self._read_json()
            key = (a or {}).get("api_key") or ""
            if not (self._authed(q) or (key and key == self.cfg.get("token"))):
                return self._send_json({"ok": False, "error": "unauthorized",
                                        "code": "unauthorized"}, 401)
        else:
            if not self._authed(q):
                return self._send_json({"ok": False, "error": "unauthorized",
                                        "code": "unauthorized"}, 401)
            a = self._read_json()
        try:
            if path == "/fs/upload/begin":
                return self._send_json(self.api.upload_begin(
                    a.get("path"), a.get("size"), a.get("md5")))
            if path == "/fs/upload/chunk":
                return self._send_json(self.api.upload_chunk(
                    a.get("upload_id"), a.get("offset", 0), a.get("data", "")))
            if path == "/fs/upload/end":
                return self._send_json(self.api.upload_end(a.get("upload_id")))
            if path == "/fs/delete":
                return self._send_json(self.api.fs_delete(a.get("path", "")))
            if path == "/fs/mkdir":
                return self._send_json(self.api.fs_mkdir(a.get("path", "")))
            if path == "/hw/reg":
                return self._send_json(self.api.hw_reg_write(
                    a.get("base"), a.get("offset"), a.get("value")))
            if path == "/hw/service":
                return self._send_json(self.api.hw_service(
                    a.get("name", ""), a.get("action", "")))
            if path == "/hw/rollback":
                return self._send_json(self.api.hw_rollback(a.get("id", "")))
            # ★★★ 转发给 agent —— 客户端只连 8768 一个端口就够 ★★★
            #
            # 踩过：接口文档里写了"转发给 agent（/tools /tool）"，
            # 但代码里只留了注释，从来没实现 —— 客户端拿到"未知接口"。
            if path == "/tool":
                return self._send_json(self.api.agent_tool(
                    a.get("name", ""), a.get("args")))
            # ★★★ /llm/* 也转发给 agent（2026-10-03 补）
            #   原因：PC 客户端的 DEFAULT_PORT=8768（网关），
            #   它保存设置时发的是 POST /llm/settings 和 POST /llm/model，
            #   而这两个接口只在 agent（8765）里 ⇒ 客户端一直拿到
            #   "未知接口: /llm/settings"，云端配置根本没生效。
            #   ⇒ 现在网关转发过去，客户端不用改一行。
            if path in ("/llm/settings", "/llm/model", "/llm/config"):
                return self._send_json(self.api.agent_post(
                    path, a, timeout=25, audit_tag="llm_" + path.split("/")[-1]))
            if path == "/voice":
                return self._send_json(self.api.agent_voice(a.get("text", "")))
            # ★★ AI 负责人任务 G/H 的推理契约（板端实现，走 PL 加速器）
            #
            # 契约（见 ai_delivery/02_文档/04_云端推理API与降级.md）：
            #   { "type": "waveform"|"chat", "data": [...], "hint": "...", "api_key": "..." }
            #   → { "ok", "label", "confidence", "detail", "elapsed_ms", "offline_mode" }
            #
            # ★ 契约里 api_key 是放在 body 里的，所以这里【不强制】Bearer 认证，
            #   但校验一下：body 里给了 api_key 就必须对；没给就走前面的 Bearer。
            #   （为了让他的 demo_offline.py / client.py 能直接用）
            if path == "/infer":
                return self._send_json(self.api.infer(a))
            if path == "/chat":
                return self._send_json(self.api.chat(
                    a.get("text", ""), a.get("session_id")))
            if path == "/chat/clear":
                return self._send_json(self.api.chat_clear(a.get("session_id")))
            # ★ 归档 / 取消归档（用户要的"归档隐藏，两边同步"）
            if path == "/chat/archive":
                return self._send_json(self.api.chat_archive(
                    a.get("session_id") or a.get("id"),
                    bool(a.get("on", True))))
            # ★ 新增：给会话改标题
            if path == "/chat/rename":
                st = self.api._sessions()
                if st is None:
                    return self._send_json({"ok": False,
                                            "error": "会话模块加载失败"})
                return self._send_json({"ok": st.rename(
                    a.get("session_id", ""), a.get("title", ""))})
            if path == "/llm/config":
                return self._send_json(self.api.llm_config(a.get("mode")))
            # ★ 设 API key（写完不回显，审计里只留前 4 位）
            if path == "/llm/key":
                return self._send_json(self.api.llm_set_key(
                    a.get("key", ""), a.get("provider", "deepseek")))
            # ★ 改完 key 要重启 agent 才生效（key 是启动时读的）
            if path == "/llm/restart":
                return self._send_json(self.api.llm_restart_agent())
            if path == "/fpga/build":
                return self._send_json(self.api.fpga_build(
                    a.get("preset", ""), a.get("desc", ""), a.get("steps"),
                    a.get("artifacts"), a.get("timeout_sec"), a.get("wait")))
            return self._send_json({"ok": False, "error": "未知接口: %s" % path}, 404)
        except Exception as e:
            import traceback
            return self._send_json({"ok": False,
                                    "error": "%s: %s" % (type(e).__name__, e),
                                    "trace": traceback.format_exc()[-500:]}, 500)


# ---------------------------------------------------------------- 发现服务
def discover_responder(port, api, stop_evt):
    """UDP 广播应答：客户端喊 XIAOBAI_DISCOVER，板子回一条 JSON"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", port))
        s.settimeout(1.0)
    except Exception as e:
        print("  ★ 发现服务起不来（端口 %d）：%s" % (port, e))
        return
    print("  发现服务在 UDP %d 上等广播" % port)
    while not stop_evt.is_set():
        try:
            data, addr = s.recvfrom(1024)
        except socket.timeout:
            continue
        except Exception:
            continue
        if b"XIAOBAI_DISCOVER" in data:
            try:
                info = api.info()
                s.sendto(json.dumps(info, ensure_ascii=False).encode("utf-8"),
                         addr)
            except Exception:
                pass
    s.close()


# ---------------------------------------------------------------- 自检
def selftest():
    ok = True

    def chk(c, m, d=""):
        nonlocal ok
        print("   %s %s%s" % ("✓" if c else "✗", m, ("   " + d) if d else ""))
        if not c:
            ok = False

    print("=" * 74)
    print(" cloud_api 自检（不起服务）")
    print("=" * 74)

    cfg = conf()
    api = Api(cfg)

    print("\n【1】配置")
    chk("token" in cfg, "有 token", cfg.get("token", "")[:4] + "****")
    chk(isinstance(cfg.get("port"), int), "端口是整数", str(cfg.get("port")))

    print("\n【2】路径白名单")
    for p, expect in [("/home/zynq/Music/a.wav", True),
                      ("/etc/passwd", False),
                      ("/home/zynq/../../etc/passwd", False),
                      ("/mnt/boot/system.bit", True),
                      ("/mnt/boot/zImage", False)]:
        got = path_ok(p)[0]
        chk(got == expect, "%-34s -> %s" % (p, "允许" if got else "拒绝"))

    print("\n【3】只读根")
    chk(not path_ok("/var/log/syslog", write=True)[0], "写 /var/log 被拒")
    chk(path_ok("/var/log/syslog", write=False)[0], "读 /var/log 允许")

    print("\n【4】信息接口")
    info = api.info()
    chk(info.get("ok"), "info 返回 ok")
    chk("temperature_c" in info, "有温度字段", str(info.get("temperature_c")))
    chk("services" in info, "有服务字段")

    print("\n【5】文件接口")
    r = api.fs_list("/home/zynq")
    chk(isinstance(r, dict), "fs_list 返回 dict")
    chk(r.get("ok") or "error" in r, "fs_list 有 ok 或 error")
    r2 = api.fs_list("/etc")
    chk(not r2.get("ok"), "列 /etc 被拒", r2.get("error", "")[:40])

    print("\n【6】硬件接口")
    rr = api.hw_regs("scope_0", "0x34")
    chk(isinstance(rr, dict) and ("ok" in rr), "hw_regs 返回 dict")
    if rr.get("ok"):
        chk(rr["regs"][0]["value"] == "0x53434F50", "scope_0 VERSION 正确",
            rr["regs"][0]["value"])
    else:
        print("      （板子不在，读不到是正常的：%s）" % rr.get("error", "")[:50])

    print("\n【7】变更历史")
    c = api.hw_changes(5)
    chk(isinstance(c, dict), "hw_changes 返回 dict")

    print("\n【8】构建任务")
    b = api.fpga_builds(5)
    chk(isinstance(b, dict), "fpga_builds 返回 dict")

    print()
    print("=" * 74)
    print(" 总体: %s" % ("★ 全部通过" if ok else "★ 有问题，看上面 ✗"))
    print("=" * 74)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--token", default=None)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--no-discover", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return 0 if selftest() else 1

    cfg = conf()
    if a.port:
        cfg["port"] = a.port
    if a.token:
        cfg["token"] = a.token

    api = Api(cfg)
    Handler.api = api
    Handler.cfg = cfg

    port = cfg["port"]
    print("=" * 74)
    print(" 云协同统一入口")
    print("=" * 74)
    print(" 端口:   %d" % port)
    print(" token:  %s****" % cfg["token"][:4])
    print(" 写权限: %s" % ("开" if cfg.get("enable_write", True) else "关"))
    print(" 审计:   %s" % AUDIT_FILE)
    print()
    print(" 客户端连上后先拉 GET /info")

    if not a.no_discover:
        evt = threading.Event()
        t = threading.Thread(target=discover_responder,
                             args=(cfg.get("discover_port", 8769), api, evt),
                             daemon=True)
        t.start()

    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(" 服务已起，Ctrl-C 退出")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n退出")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
