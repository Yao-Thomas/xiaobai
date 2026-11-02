#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hw_tools.py —— 硬件工具集（让 Agent 能真正操作板子的 PL / 音频 / 温度 / 变更单）

════════════════════════════════════════════════════════════════════
为什么要独立成一个模块
════════════════════════════════════════════════════════════════════
`tools.py` 里的工具是"通用计算机"那一套（读写文件、跑 shell、搜索…）。
硬件操作是另一类东西：

  · **更危险** —— 刷错 bitstream 板子就起不来了
  · **更慢**     —— 跑一次 Vivado 综合要十几分钟
  · **有状态**   —— 谁改了 BD、谁刷的流、能不能回滚，要留痕

所以单独一个模块，并且在 `main.py` 里显式 import 一下就会自动注册。

════════════════════════════════════════════════════════════════════
安全设计（三条硬规矩）
════════════════════════════════════════════════════════════════════
1. **只读的放行，写的一律要批准**
   reg_read / thermal / change_list 这类只读的直接跑；
   flash / hdl_edit / build 这类会改状态的，走 policy 闸门要用户点同意。

2. **静音锁优先**
   凡是会出声（acoustic_test / speak / play）的，先查 /etc/zynq-silent，
   锁着就直接拒绝 —— 这是 2026-09-28 那次事故的教训，不能绕。

3. **单写者原则**
   刷 bitstream / 改 BD 这类"全局唯一资源"的操作会先抢一个锁文件，
   避免多个 agent（DSH / Codex）同时动手把板子搞坏。

════════════════════════════════════════════════════════════════════
工具清单
════════════════════════════════════════════════════════════════════
  hw_reg_read        读 PL 寄存器（只读，放行）
  hw_thermal         温度 + 守护状态（只读，放行）
  hw_thermal_set     调温度守护阈值（写，要批准）
  hw_scope_capture   自研示波器采一段波形（只读，放行）
  hw_acoustic_test   声学自测：放音 + 录音 + 算频响（★ 过静音锁）
  hw_change_list     查硬件变更单（只读，放行）
  hw_change_add      记一条变更单（写，要批准）
  hw_flash_bitstream 刷 bitstream（★ 高危，要批准 + 单写者锁 + 自动备份）
  hw_fpga_build      跑 Vivado 综合出流（★ 高危 + 极慢，要批准）
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

from .tools import tool, REGISTRY, _policy_gate, silent_locked, SILENT_MSG  # noqa: E402,F401

# ---------------------------------------------------------------- 常量
# ★ agent 的安装目录（板上是 /home/zynq）。
#   用环境变量可以指到别处 —— 方便在 PC 上离线测这条链。
AGENT_DIR = os.environ.get("XIAOBAI_AGENT_DIR", "/home/zynq")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

# PL 里各个自研 IP 的基地址（和 07_接口约定单.md 一致）
PL_MAP = {
    "lcd_id":        0x41200000,
    "axi_gpio":      0x41210000,
    "gpu_0":         0x43CB0000,
    "scope_0":       0x43CC0000,
    "cnn_conv_pool": 0x43CD0000,
    "cnn_fc":        0x43CE0000,
    "audio_fmt":     0x43C50000,
    "i2s_rx":        0x43C60000,
    "i2s_tx":        0x43C70000,
    "pwm_backlight": 0x43C00000,
}

# 全局唯一资源锁（防止多个 agent 同时刷流/改 BD）
LOCK_DIR = "/run/hwlock"
BITSTREAM = "/mnt/boot/system.bit"

# 变更单目录
CHANGE_DIR = "/var/lib/hwchange"
CHANGE_FILE = CHANGE_DIR + "/changes.jsonl"

# 温度守护
THERMAL_STATE = "/run/thermal/state.json"
THERMAL_SCRIPT = "/home/zynq/thermal_guard.py"

TEMP_RAW = "/sys/bus/iio/devices/iio:device0/in_temp0_raw"
TEMP_SCALE = "/sys/bus/iio/devices/iio:device0/in_temp0_scale"
TEMP_OFFSET = "/sys/bus/iio/devices/iio:device0/in_temp0_offset"


# ---------------------------------------------------------------- 小工具
def _sh(cmd, timeout=60):
    """跑一条命令，返回 (rc, stdout+stderr)"""
    try:
        p = subprocess.run(cmd, shell=isinstance(cmd, str),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=timeout)
        return p.returncode, (p.stdout or b"").decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return -1, "[超时 %ds]" % timeout
    except Exception as e:
        return -1, "%s: %s" % (type(e).__name__, e)


def _need_root_hint():
    return "（提示：这个操作要 root，Agent 服务以 root 跑才行；看 zynq-agent.service 的 User=）"


def _safe_int(v, default, lo=None, hi=None):
    """把模型给的参数安全地转成 int

    ★ 为什么需要：模型经常把数字传成字符串（"10"），偶尔还会给"abc"或者
      干脆给个 dict。工具函数**永远不能抛异常**（tools.call 会把异常变成
      错误字符串回给模型，那样模型会以为是工具坏了，而不是自己传错了），
      所以这里统一兜住，错了就用默认值。
    """
    try:
        n = int(float(v)) if not isinstance(v, bool) else int(v)
    except Exception:
        return default
    if lo is not None and n < lo:
        n = lo
    if hi is not None and n > hi:
        n = hi
    return n


def _read_temp():
    """读 XADC 片上温度"""
    try:
        raw = int(open(TEMP_RAW).read().strip())
        sc = float(open(TEMP_SCALE).read().strip())
        off = float(open(TEMP_OFFSET).read().strip())
        return (raw + off) * sc / 1000.0
    except Exception:
        return None


def _read_pl_reg(base, off, width=4):
    """读一个 PL 寄存器。★ 用子进程读，因为访问空地址会 SIGBUS 打死整个进程。

    这一点是踩过坑的：直接在本进程 mmap 一个没映射的 PL 地址，
    第一次读就会 SIGBUS，Agent 服务直接挂。所以每次都 fork 一个子进程去读。
    """
    code = (
        "import mmap,os,struct,sys\n"
        "base=%d; off=%d; width=%d\n"
        "try:\n"
        "    fd=os.open('/dev/mem', os.O_RDONLY|os.O_SYNC)\n"
        "    m=mmap.mmap(fd, 4096, mmap.MAP_SHARED, mmap.PROT_READ, offset=base)\n"
        "    if width==4:\n"
        "        v=struct.unpack_from('<I', m, off)[0]\n"
        "    else:\n"
        "        v=int.from_bytes(m[off:off+width], 'little')\n"
        # ★ 用 str.format，别用 %-格式化 —— 外层已经有一次 % 替换了，
        #   内层再写 %%0%dx 会变成 %0%dx，%d 被外层吃掉（踩过这个坑）
        "    print('0x{:0{w}x}'.format(v, w=width*2))\n"
        "except Exception as e:\n"
        "    sys.exit('ERR:'+str(e))\n"
    ) % (base, off, width)
    rc, out = _sh(["python3", "-c", code], timeout=10)
    out = out.strip()
    if rc != 0 or out.startswith("ERR:") or not out:
        return None, out or "读失败"
    return out, None


def _write_pl_reg(base, off, val):
    code = (
        "import mmap,os,struct,sys\n"
        "base=%d; off=%d; val=%d\n"
        "try:\n"
        "    fd=os.open('/dev/mem', os.O_RDWR|os.O_SYNC)\n"
        "    m=mmap.mmap(fd, 4096, mmap.MAP_SHARED,"
        " mmap.PROT_READ|mmap.PROT_WRITE, offset=base)\n"
        "    struct.pack_into('<I', m, off, val & 0xFFFFFFFF)\n"
        "    print('OK')\n"
        "except Exception as e:\n"
        "    sys.exit('ERR:'+str(e))\n"
    ) % (base, off, val)
    rc, out = _sh(["python3", "-c", code], timeout=10)
    return rc == 0 and out.strip() == "OK", out.strip()


class _Lock(object):
    """简单的全局单写者锁"""

    def __init__(self, name):
        self.path = os.path.join(LOCK_DIR, name + ".lock")
        self.got = False

    def __enter__(self):
        try:
            os.makedirs(LOCK_DIR, exist_ok=True)
            if os.path.exists(self.path):
                try:
                    age = time.time() - os.path.getmtime(self.path)
                except OSError:
                    age = 0
                # 超过 40 分钟认为是死锁（例如上个 agent 崩了）
                if age < 40 * 60:
                    owner = open(self.path).read().strip()
                    raise RuntimeError(
                        "★ 【单写者锁】%s 正被占用（%s，%.0f 秒前）。\n"
                        "  这一步是全局唯一资源操作，同一时间只能一个人做。\n"
                        "  等对方做完，或确认它挂了再手工删 %s"
                        % (name, owner or "?", age, self.path))
            with open(self.path, "w", encoding="utf-8") as f:
                f.write("pid=%d %s" % (os.getpid(),
                                       time.strftime("%H:%M:%S")))
            self.got = True
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError("抢锁失败: %s" % e)
        return self

    def __exit__(self, *a):
        if self.got:
            try:
                os.remove(self.path)
            except OSError:
                pass


def _add_change(kind, detail, result, who="agent", extra=None):
    """记一条变更单

    ★★★ 2026-10-02 修正：以前这里是【自己拼一个 dict 写文件】，
    没有 id 字段；而 hw_change.py 里的 change_add() 会生成 id。
    结果两套格式混在一份 JSONL 里，按 id 回滚时就 KeyError
    （离线测试抓出来的）。

    ⇒ 现在统一委托给 hw_change.change_add，保证【只有一套格式】。
    """
    try:
        try:
            from . import hw_change as _HC
            # 让 hw_change 用同一个目录（板子上是 /var/lib/hwchange，
            # 测试时可能被改到临时目录）
            if getattr(_HC, "CHANGE_FILE", None) != CHANGE_FILE:
                _HC.CHANGE_DIR = os.path.dirname(CHANGE_FILE)
                _HC.CHANGE_FILE = CHANGE_FILE
                _HC.SNAPSHOT_DIR = os.path.join(_HC.CHANGE_DIR, "snapshots")
            _HC.change_add(kind, detail, result, who, extra=extra)
            return True
        except Exception:
            # 退路：hw_change 用不了时，至少自己写的记录也要带 id
            os.makedirs(os.path.dirname(CHANGE_FILE), exist_ok=True)
            rec = {
                "id": time.strftime("%Y%m%d_%H%M%S") + "_%04d"
                      % (int(time.time() * 997) % 10000),
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "kind": kind,
                "detail": detail,
                "result": result,
                "who": who,
            }
            with open(CHANGE_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════
#  只读工具（直接放行）
# ══════════════════════════════════════════════════════════════════
@tool("hw_reg_read",
      "读 PL（FPGA 逻辑）里某个寄存器的值。用于确认自研 IP 在线、看状态。"
      "只读、安全。base 可以给名字（gpu_0/scope_0/cnn_conv_pool/cnn_fc/…）"
      "或十六进制地址。读不存在的地址会返回错误（不会把服务搞崩）。",
      {"type": "object",
       "properties": {
           "base": {"type": "string",
                    "description": "IP 名字或地址，如 scope_0 或 0x43CC0000"},
           "offset": {"type": "string", "description": "寄存器偏移，如 0x34"},
           "count": {"type": "integer",
                     "description": "连读几个 32 位寄存器（默认 1，最多 16）"},
           "width": {"type": "integer", "description": "位宽 4 或 1，默认 4"},
       },
       "required": ["base"]})
def _hw_reg_read(a, ctx):
    base_s = str(a.get("base", "")).strip()
    base = PL_MAP.get(base_s)
    if base is None:
        try:
            base = int(base_s, 0)
        except Exception:
            return ("错误：base 要给已知 IP 名字（%s）或十六进制地址"
                    % ", ".join(sorted(PL_MAP)))
    try:
        off0 = int(str(a.get("offset", "0")), 0)
    except Exception:
        return "错误：offset 要像 0x00 这样"
    cnt = _safe_int(a.get("count"), 1, 1, 16)
    width = 4 if _safe_int(a.get("width"), 4) == 4 else 1

    lines = ["PL 寄存器读取  base=0x%08X" % base]
    got = 0
    for i in range(cnt):
        off = off0 + i * 4
        v, err = _read_pl_reg(base, off, width)
        if v is None:
            lines.append("  +0x%02X  ★ 读不到（%s）——这个地址在 PL 里没有映射"
                         % (off, err))
            break
        lines.append("  +0x%02X = %s" % (off, v))
        got += 1
    if got == 0:
        lines.append("（一个都没读到：可能 bitstream 没刷、或地址不对）")
    else:
        lines.append("（读到 %d 个，说明这一段地址在 PL 里有东西）" % got)
    return "\n".join(lines)


@tool("hw_thermal",
      "读板子温度 + 温度守护当前状态（等级、阈值、已降载了哪些服务）。"
      "只读、安全。板子没有风扇也没有 cpufreq，所以只能靠停负载/重启降温。",
      {"type": "object", "properties": {}})
def _hw_thermal(a, ctx):
    t = _read_temp()
    out = []
    if t is None:
        out.append("温度：★ 读不到（XADC 驱动在不在？看 /sys/bus/iio/devices/）")
    else:
        out.append("片上温度：%.1f °C" % t)
    try:
        st = json.load(open(THERMAL_STATE))
        out.append("守护等级：%s   峰值：%s °C" % (st.get("level"),
                                                  st.get("peak")))
        out.append("阈值：%s" % st.get("thresholds"))
        if st.get("stopped"):
            out.append("已降载：%s" % ", ".join(st["stopped"]))
        else:
            out.append("已降载：无")
        out.append("更新时间：%s" % st.get("time"))
    except Exception as e:
        out.append("守护状态读不到（%s）—— thermal-guard 服务在跑吗？" % e)
    return "\n".join(out)


@tool("hw_scope_capture",
      "用板上的自研示波器 IP 采一段波形。"
      "默认返回统计（采样率/峰峰值/占空比/估算频率/触发点）；"
      "给 raw=true 则返回 4096 个原始 8 位样本（波形 AI 用这个）。"
      "可以顺便设内部 DDS（src=0 时给 wave/freq_hz）来自造信号。"
      "只读、安全。",
      {"type": "object",
       "properties": {
           "src": {"type": "integer",
                   "description": "0=内部 DDS（默认），1=外部 XADC"},
           "dec": {"type": "integer",
                   "description": "抽取 1~255（越大每点时间越长），默认 1"},
           "trig_level": {"type": "integer", "description": "触发电平 0~255，默认 128"},
           "trig_edge": {"type": "integer", "description": "0=上升（默认），1=下降"},
           "trig_mode": {"type": "integer",
                         "description": "0=Auto（默认），1=Normal，2=Single"},
           "timeout_ms": {"type": "integer", "description": "等待超时，默认 500"},
           "raw": {"type": "boolean",
                   "description": "true 则返回 4096 个原始样本而不是统计"},
           "wave": {"type": "integer",
                    "description": "先设 DDS 波形 0=正弦 1=方波 2=三角 3=锯齿"},
           "freq_hz": {"type": "number", "description": "先设 DDS 频率（Hz）"},
       }})
def _hw_scope_capture(a, ctx):
    """★ 2026-10-02 改成调 scope_capture.py（接口 ③ 的实现）

    以前这个工具是 `python3 scope.py --secs ... --points ...` —— 那个 CLI
    参数根本不存在，所以从来没成功过。
    现在走约定好的接口：capture_once() 返回
    {ok, samples[4096], fs_hz, trig_pos, meta}。
    """
    try:
        sys.path.insert(0, AGENT_DIR)
        import scope_capture as SC
    except Exception:
        # 退路：试着从几个位置 import
        for p in ("/home/zynq", "/home/zynq/ui", os.path.dirname(__file__)):
            if p not in sys.path:
                sys.path.insert(0, p)
        try:
            import scope_capture as SC
        except Exception as e:
            return ("找不到 scope_capture.py（%s）。\n"
                    "它是『接口 ③：示波器读取接口』的实现，"
                    "应该放在 /home/zynq/scope_capture.py。" % e)

    out = []

    # ---- 可选：先设 DDS ----
    #
    # ★★★ 这里【不能】用 _safe_int 钳位（离线测试抓出来的）：
    #   _safe_int(9, 0, 0, 3) 会把 9 悄悄变成 3，于是 set_dds 的参数校验
    #   永远收不到越界值，agent 以为设了波形 9 实际得到波形 3 —— 静默错误。
    #   ⇒ 原样传下去，让 set_dds 明确拒绝。
    if a.get("wave") is not None and a.get("freq_hz") is not None:
        try:
            wave = int(a.get("wave"))
        except Exception:
            return "wave 要是 0~3 的整数（0正弦 1方波 2三角 3锯齿）"
        try:
            fhz = float(a.get("freq_hz"))
        except Exception:
            return "freq_hz 要是数字"
        d = SC.set_dds(wave, fhz)
        if not d.get("ok"):
            return "设 DDS 失败：%s" % d.get("error")
        out.append("已设 DDS：波形 %d（%s），频率 %.1f Hz"
                   % (d["waveform"],
                      ["正弦", "方波", "三角", "锯齿"][d["waveform"]],
                      d["freq_hz"]))

    # ---- 采集 ----
    r = SC.capture_once(
        src=_safe_int(a.get("src"), 0, 0, 1),
        dec=_safe_int(a.get("dec"), 1, 1, 255),
        trig_level=_safe_int(a.get("trig_level"), 128, 0, 255),
        trig_edge=_safe_int(a.get("trig_edge"), 0, 0, 1),
        trig_mode=_safe_int(a.get("trig_mode"), 0, 0, 2),
        timeout_ms=_safe_int(a.get("timeout_ms"), 500, 10, 10000))

    if not r.get("ok"):
        return "采集失败：%s" % r.get("error")

    meta = r.get("meta") or {}
    if a.get("raw"):
        s = r["samples"]
        out.append("原始样本 %d 个（0~255），采样率 %.0f Hz，触发点 %d"
                   % (len(s), r["fs_hz"], r["trig_pos"]))
        out.append("samples: " + ",".join(str(v) for v in s))
        return "\n".join(out)

    out.append("采样率 %.0f Hz（每点 %.3g 秒）  源：%s"
               % (r["fs_hz"], 1.0 / r["fs_hz"], meta.get("src", "?")))
    out.append("峰峰值 %s（min %s / max %s）  均值 %s"
               % (meta.get("vpp"), meta.get("min"), meta.get("max"),
                  meta.get("mean")))
    out.append("估算频率 %s Hz   占空比 %s"
               % (meta.get("freq_hz"), meta.get("duty")))
    out.append("触发点位置 %d   用时 %s ms"
               % (r["trig_pos"], meta.get("elapsed_ms")))
    out.append("")
    out.append("★ 想看原始波形用 hw_waveform_classify（它会自己做 STFT + 分类）")
    return "\n".join(out)


@tool("hw_change_list",
      "查硬件变更单（谁在什么时候改了什么、结果如何）。"
      "改 BD / 刷 bitstream / 改驱动前先查这个，避免和别人的改动冲突。只读、安全。",
      {"type": "object",
       "properties": {
           "limit": {"type": "integer", "description": "返回最近几条，默认 10"},
       }})
def _hw_change_list(a, ctx):
    # ★ 参数要能容错：模型有时候会传 "10" 或者干脆传个乱七八糟的东西，
    #   不能因为一个 int() 就把整个工具搞崩（工具必须永远返回字符串）
    n = _safe_int(a.get("limit"), 10, 1, 100)
    if not os.path.exists(CHANGE_FILE):
        return "还没有任何变更单记录（%s 不存在）" % CHANGE_FILE
    try:
        lines = open(CHANGE_FILE).read().splitlines()
    except Exception as e:
        return "读变更单失败：%s" % e
    if not lines:
        return "变更单是空的"
    out = ["最近 %d 条变更单：" % min(n, len(lines))]
    for ln in lines[-n:]:
        try:
            r = json.loads(ln)
            out.append("  [%s] %s  %s  -> %s  (by %s)"
                       % (r.get("ts"), r.get("kind"), r.get("detail"),
                          r.get("result"), r.get("who")))
        except Exception:
            out.append("  " + ln[:160])
    return "\n".join(out)


# ══════════════════════════════════════════════════════════════════
#  会出声的工具（★ 必须先过静音锁）
# ══════════════════════════════════════════════════════════════════
@tool("hw_acoustic_test",
      "声学自测：放一个已知频率的纯音，用麦克风录回来，算『放音/静音』的"
      "能量比值来判断麦克风和喇叭通不通。"
      "★ 会出声，所以受静音锁约束：用户没明确同意前会被拒绝。",
      {"type": "object",
       "properties": {
           "freq": {"type": "number", "description": "频率 Hz，默认 990.53"},
           "secs": {"type": "number", "description": "每次时长秒，默认 1.2"},
           "vol": {"type": "integer", "description": "音量 0-192，默认 33"},
           "sweep": {"type": "boolean", "description": "扫多个频点看频响"},
       }})
def _hw_acoustic_test(a, ctx):
    if silent_locked():
        return SILENT_MSG
    script = "/home/zynq/acoustic_selftest.py"
    if not os.path.exists(script):
        return ("没找到 %s。这个脚本要在 PC 侧写好再传上来：\n"
                "  它是『放已知频率 + 录音 + Goertzel 算比值』的完整实现。\n"
                "★ 注意判据要用 play/base 的比值，不能找最大能量 —— "
                "基线有 100Hz 工频谐波，找最大能量会误判。" % script)
    cmd = ["python3", script]
    if a.get("freq"):
        cmd += ["--freq", str(a["freq"])]
    if a.get("secs"):
        cmd += ["--secs", str(a["secs"])]
    if a.get("vol"):
        cmd += ["--vol", str(a["vol"])]
    if a.get("sweep"):
        cmd += ["--sweep"]
    rc, out = _sh(cmd, timeout=180)
    _add_change("acoustic_test", "freq=%s sweep=%s" % (a.get("freq"),
                                                       a.get("sweep")),
                "rc=%d" % rc)
    return "声学自测：\n" + out[-3000:]


# ══════════════════════════════════════════════════════════════════
#  写操作（★ 一律要用户批准）
# ══════════════════════════════════════════════════════════════════
@tool("hw_change_add",
      "记一条硬件变更单（改了 BD / 刷了流 / 动了驱动 / 改了接口约定之后都要记）。"
      "会写盘，需要用户批准。",
      {"type": "object",
       "properties": {
           "kind": {"type": "string",
                    "description": "类型：bd / bitstream / driver / iface / other"},
           "detail": {"type": "string", "description": "改了什么"},
           "result": {"type": "string", "description": "结果/影响"},
       },
       "required": ["kind", "detail"]})
def _hw_change_add(a, ctx):
    kind = str(a.get("kind", ""))[:40]
    detail = str(a.get("detail", ""))[:500]
    result = str(a.get("result", ""))[:300]
    g = _policy_gate("write", "hw_change_add: %s %s" % (kind, detail))
    if g:
        return g
    ok = _add_change(kind, detail, result, who="agent")
    return ("已记录变更单：%s" % (CHANGE_FILE if ok else "★ 写失败（权限？）"))


@tool("hw_flash_bitstream",
      "★★ 高危：把 bitstream 刷进 SD 卡的启动分区，重启后才生效。"
      "内部做了三件保护：① 要用户批准 ② 抢全局单写者锁 ③ 先备份现有流。"
      "写入是原子的（写 .new -> 校验 md5 -> mv），避免断电留半截文件。",
      {"type": "object",
       "properties": {
           "file": {"type": "string", "description": "要刷的 .bit 文件路径"},
           "md5": {"type": "string", "description": "期望的 md5（可选，给了就校验）"},
           "reboot": {"type": "boolean",
                      "description": "刷完是否立刻重启（默认 false，手动重启更安全）"},
       },
       "required": ["file"]})
def _hw_flash_bitstream(a, ctx):
    src = str(a.get("file", "")).strip()
    if not src or not os.path.exists(src):
        return "错误：找不到 bitstream 文件 %r" % src
    size = os.path.getsize(src)
    if size < 100000:
        return ("错误：%s 只有 %d 字节，不像 bitstream（正常约 4MB）。"
                "拒绝刷写以免把启动分区搞坏。" % (src, size))

    g = _policy_gate("shell", "flash bitstream %s -> %s" % (src, BITSTREAM))
    if g:
        return g

    try:
        with _Lock("bitstream"):
            # 1) 校验
            rc, want = _sh(["md5sum", src])
            if rc != 0:
                return "md5sum 失败：%s" % want
            got = want.split()[0]
            exp = (a.get("md5") or "").strip().lower()
            if exp and got != exp:
                return "★ md5 不符，中止（期望 %s，实际 %s）" % (exp, got)

            # 2) 挂启动分区
            _sh(["mountpoint", "-q", "/mnt/boot"], 10)
            rc, out = _sh(["sh", "-c",
                           "mountpoint -q /mnt/boot || mount /dev/mmcblk0p1 /mnt/boot"],
                          15)
            if not os.path.exists("/mnt/boot/BOOT.BIN"):
                _sh(["umount", "/mnt/boot"], 10)
                return "★ /mnt/boot 里没有 BOOT.BIN，不像启动分区，中止"

            # 3) 备份
            ts = time.strftime("%Y%m%d_%H%M%S")
            bak = "/mnt/boot/system.bit.bak_agent_%s" % ts
            rc, out = _sh(["cp", BITSTREAM, bak], 60)
            if rc != 0:
                _sh(["umount", "/mnt/boot"], 10)
                return "★ 备份失败（%s），中止。权限？" % out.strip()

            # 4) 原子写
            rc, out = _sh(["cp", src, "/mnt/boot/system.bit.new"], 120)
            if rc != 0:
                _sh(["umount", "/mnt/boot"], 10)
                return "★ 写 .new 失败：%s" % out.strip()
            _sh(["sync"], 60)
            rc, out = _sh(["md5sum", "/mnt/boot/system.bit.new"])
            newmd5 = out.split()[0] if out else ""
            if newmd5 != got:
                _sh(["rm", "-f", "/mnt/boot/system.bit.new"], 10)
                _sh(["umount", "/mnt/boot"], 10)
                return "★ .new 校验失败（%s != %s），原文件未动，已清理" % (newmd5, got)
            rc, out = _sh(["mv", "/mnt/boot/system.bit.new", BITSTREAM], 60)
            _sh(["sync"], 60)
            _sh(["umount", "/mnt/boot"], 10)

        _add_change("bitstream", "%s -> %s (md5 %s)" % (src, BITSTREAM, got),
                    "成功，备份 %s" % bak)
        msg = ["★ bitstream 已刷入（重启后生效）",
               "  文件：%s（%d 字节）" % (src, size),
               "  md5：%s" % got,
               "  备份：%s   ← 要回滚就把它 mv 回 system.bit" % bak]
        if a.get("reboot"):
            _sh(["sync"], 60)
            _sh(["systemctl", "reboot"], 20)
            msg.append("  已发起重启")
        else:
            msg.append("  ★ 还没重启。确认无误后再说一声，或者自己重启。")
        return "\n".join(msg)
    except RuntimeError as e:
        return str(e)


@tool("hw_fpga_build",
      "★★ 让 agent 真的跑 Vivado（HLS 综合 / 综合+实现+出流）。"
      "板子跑不动 Vivado，所以走【文件队列】：本工具把任务写到 "
      "/home/zynq/fpga_jobs/<id>.request.json，PC 上的 fpga_build_daemon.py "
      "轮询取走、跑 Vivado、把结果写回 <id>.result.json。"
      "这是『agent 能改自己硬件』的构建环节。需要用户批准。",
      {"type": "object",
       "properties": {
           "preset": {"type": "string",
                      "description": "预设任务：hls_all(HLS 全部综合) / "
                                     "bitstream(完整出流) / check(只查工程状态)。"
                                     "给了 preset 就不用给 steps"},
           "desc": {"type": "string", "description": "这次构建在干什么"},
           "steps": {
               "type": "array",
               "description": "自定义步骤（不给 preset 时用）",
               "items": {"type": "object",
                         "properties": {"desc": {"type": "string"},
                                        "cmd": {"type": "string"},
                                        "cwd": {"type": "string"}},
                         "required": ["cmd"]}},
           "artifacts": {
               "type": "array",
               "description": "关心的产物路径（PC 上的路径）",
               "items": {"type": "string"}},
           "timeout_sec": {"type": "integer",
                           "description": "总超时秒，默认 3600"},
           "wait": {"type": "boolean",
                    "description": "是否等构建完成（默认 true）。"
                                   "false 就只提交任务立刻返回"},
           "wait_max_sec": {"type": "integer",
                            "description": "最多等多少秒，默认 2400"},
       }})
def _hw_fpga_build(a, ctx):
    g = _policy_gate("shell", "vivado build: %s"
                     % (a.get("desc") or a.get("preset") or ""))
    if g:
        return g

    import time as _time

    # ★ 任务目录可以用环境变量覆盖，方便在 PC 上离线测这条链
    JOBS = os.environ.get("FPGA_JOBS_DIR", "/home/zynq/fpga_jobs")
    jid = _time.strftime("%Y%m%d_%H%M%S") + "_%03d" % (os.getpid() % 1000)

    # ---- 组装步骤 ----
    preset = (a.get("preset") or "").strip()
    steps = a.get("steps") or []
    arts = a.get("artifacts") or []

    if preset and not steps:
        if preset == "hls_all":
            # ★★★ 2026-10-03 修：原来指向 D:\ubuntu_iso\run_build_hls.bat
            #   —— 那个文件【根本不存在】，所以 preset=hls_all 一用就报
            #   "不是内部或外部命令"。
            #   实际脚本在 cnn_hls_2026\build_all.bat：
            #   跑两个 HLS 核（conv_pool + fc），各自 v++ -c --mode hls。
            #   产物已确认存在：conv_pool 197KB / fc 170KB。
            steps = [{"desc": "跑 HLS 综合（两个核）",
                      "cmd": 'cmd /c "cd /d D:\\ubuntu_iso\\cnn_hls_2026 '
                             '&& call build_all.bat"'}]
            arts = ["cnn_hls_2026/work/conv_pool/cnn_conv_pool_q.zip",
                    "cnn_hls_2026/work/fc/cnn_fc_q.zip"]
        elif preset == "bitstream":
            steps = [{"desc": "跑 Vivado 综合+实现+出流",
                      "cmd": 'cmd /c "cd /d D:\\ubuntu_iso && call '
                             'run_build_cnn.bat"'}]
            arts = ["atk2026/Navigator_7020/Navigator_7020.runs/impl_1/"
                    "system_wrapper.bit"]
        elif preset == "check":
            steps = [{"desc": "查工程状态",
                      "cmd": 'cmd /c "call D:\\Xilinx\\2026.1\\Vivado\\'
                             'settings64.bat >nul 2>&1 && vivado -mode batch '
                             '-source D:\\ubuntu_iso\\check_project.tcl '
                             '-log D:\\ubuntu_iso\\fpga_jobs\\_check.log"'}]
            arts = ["fpga_jobs/_vivado_report.txt"]
        else:
            return ("错误：preset 只支持 hls_all / bitstream / check，"
                    "或者你自己给 steps")

    if not steps:
        return "错误：要么给 preset，要么给 steps（至少一步）"

    req = {
        "id": jid,
        "ts": _time.strftime("%Y-%m-%d %H:%M:%S"),
        "kind": preset or "custom",
        "desc": a.get("desc") or ("预设构建: %s" % preset if preset else "自定义构建"),
        "steps": steps,
        "artifacts": arts,
        "timeout_sec": _safe_int(a.get("timeout_sec"), 3600, 60, 86400),
        "who": "zynq-agent",
    }

    # ---- 写任务 ----
    try:
        os.makedirs(JOBS, exist_ok=True)
        rp = os.path.join(JOBS, jid + ".request.json")
        with open(rp, "w", encoding="utf-8") as f:
            json.dump(req, f, ensure_ascii=False, indent=1)
    except Exception as e:
        return "写任务失败：%s" % e

    _add_change("build", "提交构建任务 %s: %s" % (jid, req["desc"]), "已提交")

    out = ["★ 构建任务已提交", "  任务号：%s" % jid,
           "  内容：%s" % req["desc"],
           "  步骤：%d 步" % len(steps),
           "  任务文件：%s" % rp,
           "",
           "★ PC 侧要跑着 fpga_build_daemon.py 才会执行：",
           "    python fpga_build_daemon.py        （在 D:\\ubuntu_iso 下）"]

    if not a.get("wait", True):
        out.append("")
        out.append("（wait=false，不等待。之后用 hw_fpga_build_status 查）")
        return "\n".join(out)

    # ---- 等结果 ----
    wp = os.path.join(JOBS, jid + ".result.json")
    t0 = _time.time()
    maxw = _safe_int(a.get("wait_max_sec"), 2400, 10, 86400)
    out.append("")
    out.append("等待构建完成（最多 %d 秒）…" % maxw)
    while _time.time() - t0 < maxw:
        if os.path.exists(wp):
            try:
                res = json.load(open(wp, encoding="utf-8"))
            except Exception:
                _time.sleep(2)
                continue
            out.append("")
            out.append("★ 构建结果：%s   用时 %.0f 秒"
                       % (res.get("status"), res.get("elapsed_sec", 0)))
            for st in res.get("steps", []):
                out.append("  [rc=%s] %s  (%.0fs)"
                           % (st.get("rc"), st.get("desc"), st.get("elapsed", 0)))
                if st.get("rc") != 0 and st.get("tail"):
                    out.append("     最后几行：")
                    for ln in st["tail"].split("\n")[-6:]:
                        out.append("       " + ln[:150])
            for ar in res.get("artifacts", []):
                if ar.get("missing"):
                    out.append("  产物缺失: %s" % ar["path"])
                else:
                    out.append("  产物: %s  %d 字节  md5=%s"
                               % (ar["path"], ar["size"], ar["md5"]))
            if res.get("error"):
                out.append("  错误: %s" % res["error"])
            out.append("")
            if res.get("status") == "ok":
                out.append("⇒ 下一步：用 hw_flash_bitstream 刷到板子，"
                           "再用 hw_verify 跑回归")
            else:
                out.append("⇒ 构建没成功。改回去重来，或用 hw_change_rollback 回滚")
            _add_change("build", "构建任务 %s 结果 %s" % (jid, res.get("status")),
                        res.get("error") or "ok")
            return "\n".join(out)
        _time.sleep(5)

    out.append("")
    out.append("★ 等了 %d 秒还没出结果。" % maxw)
    out.append("  可能原因：① PC 侧守护没在跑 ② 构建确实很慢（出流要 20-50 分钟）")
    out.append("  之后用 hw_fpga_build_status --id %s 查结果" % jid)
    return "\n".join(out)


@tool("hw_fpga_build_status",
      "查某个构建任务的状态/结果。只读、安全。",
      {"type": "object",
       "properties": {
           "id": {"type": "string", "description": "任务号；不给就列最近几个"},
           "limit": {"type": "integer", "description": "列多少个，默认 5"},
       }})
def _hw_fpga_build_status(a, ctx):
    JOBS = os.environ.get("FPGA_JOBS_DIR", "/home/zynq/fpga_jobs")
    jid = (a.get("id") or "").strip()
    if jid:
        rp = os.path.join(JOBS, jid + ".result.json")
        qp = os.path.join(JOBS, jid + ".request.json")
        if os.path.exists(rp):
            try:
                res = json.load(open(rp, encoding="utf-8"))
            except Exception as e:
                return "结果文件读不了：%s" % e
            lines = ["任务 %s：%s  用时 %.0f 秒"
                     % (jid, res.get("status"), res.get("elapsed_sec", 0))]
            for st in res.get("steps", []):
                lines.append("  [rc=%s] %s" % (st.get("rc"), st.get("desc")))
            for ar in res.get("artifacts", []):
                if ar.get("missing"):
                    lines.append("  产物缺失: %s" % ar["path"])
                else:
                    lines.append("  产物: %s  %d 字节  md5=%s"
                                 % (ar["path"], ar["size"], ar["md5"]))
            if res.get("error"):
                lines.append("  错误: %s" % res["error"])
            return "\n".join(lines)
        if os.path.exists(qp):
            return ("任务 %s 已提交但**还没结果** —— PC 侧守护在跑吗？\n"
                    "  （python fpga_build_daemon.py）" % jid)
        return "没有这个任务：%s" % jid

    n = _safe_int(a.get("limit"), 5, 1, 50)
    if not os.path.isdir(JOBS):
        return "还没有任何构建任务（%s 不存在）" % JOBS
    reqs = sorted(f for f in os.listdir(JOBS) if f.endswith(".request.json"))
    if not reqs:
        return "没有构建任务"
    lines = ["最近 %d 个构建任务：" % min(n, len(reqs))]
    for f in reqs[-n:]:
        j = f[:-len(".request.json")]
        r = os.path.join(JOBS, j + ".result.json")
        status = "待处理"
        if os.path.exists(r):
            try:
                status = json.load(open(r, encoding="utf-8")).get("status")
            except Exception:
                status = "结果坏了"
        lines.append("  %-24s %s" % (j, status))
    return "\n".join(lines)


def _strip_hdl_comments(txt):
    """去掉 Verilog/SystemVerilog 的注释和字符串，再去做括号/关键字配平检查

    ★ 为什么要这一步：直接 count("module") 会把注释里的词也数进去。
      我第一版就踩了：原文件注释里写着 "// scope_cap.v —— 示波器采集"，
      加上代码里的 module，数量变成 2，而 endmodule 是 1 —— 于是把
      一个完全合法的改动判成了"不配平"，拦住了。

    ★★★ 这个函数必须放在 @tool 装饰器【之前】★★★
      放后面的话，装饰器会套到它头上（Python 的装饰器作用于紧接着的那个 def），
      结果 "hw_hdl_edit" 这个工具名指向 _strip_hdl_comments，
      调用时报 "takes 1 positional argument but 2 were given"。
      （离线测试抓出来的 —— 好好的工具全废了）
    """
    import re as _re2
    txt = _re2.sub(r"/\*.*?\*/", " ", txt, flags=_re2.S)   # 块注释
    txt = _re2.sub(r"//[^\n]*", " ", txt)                  # 行注释
    txt = _re2.sub(r'"[^"\n]*"', '""', txt)                # 字符串（粗略）
    return txt


@tool("hw_hdl_edit",
      "★ 改 RTL / block design / 约束文件。这是『agent 改 FPGA』的编辑环节。"
      "内部做三件保护：① 要用户批准 ② 自动备份 ③ 改完做基础语法/一致性检查。"
      "配合 hw_fpga_build（重新综合）+ hw_flash_bitstream（刷流）+ hw_verify（回归）"
      "就是完整的改硬件闭环。",
      {"type": "object",
       "properties": {
           "file": {"type": "string", "description": "要改的文件路径"},
           "old": {"type": "string",
                   "description": "要被替换的原文（必须唯一匹配）"},
           "new": {"type": "string", "description": "替换成什么"},
           "create": {"type": "boolean",
                      "description": "true 表示新建文件（这时不用给 old）"},
           "note": {"type": "string",
                    "description": "这次改动的说明（会记进变更单）"},
       },
       "required": ["file"]})
def _hw_hdl_edit(a, ctx):
    import re as _re
    import shutil as _shutil

    fp = str(a.get("file") or "").strip()
    note = str(a.get("note") or "")[:300]
    if not fp:
        return "错误：要给 file"

    g = _policy_gate("write", "hdl_edit %s: %s" % (fp, note))
    if g:
        return g

    # ---- 新建 ----
    if a.get("create"):
        if os.path.exists(fp):
            return "错误：%s 已存在。要改的话用 old/new（不要用 create）" % fp
        try:
            os.makedirs(os.path.dirname(fp) or ".", exist_ok=True)
            with open(fp, "w", encoding="utf-8") as f:
                f.write(str(a.get("new") or ""))
        except Exception as e:
            return "新建失败：%s" % e
        _add_change("hdl", "新建 %s: %s" % (fp, note), "成功")
        return "✓ 已新建 %s（%d 字节）" % (fp, os.path.getsize(fp))

    # ---- 修改 ----
    if not os.path.exists(fp):
        return "错误：找不到 %s" % fp
    old = a.get("old")
    new = a.get("new")
    if old is None or new is None:
        return "错误：修改文件要给 old 和 new"
    old = str(old)
    new = str(new)

    try:
        src = open(fp, encoding="utf-8").read()
    except Exception as e:
        return "读文件失败：%s" % e

    cnt = src.count(old)
    if cnt == 0:
        return ("错误：在 %s 里找不到要替换的原文。\n"
                "  给你看一下 old 的前 80 字：%s\n"
                "  ⇒ 先用 read 工具把文件读出来，照抄准确的原文" % (fp, old[:80]))
    if cnt > 1:
        return ("错误：要替换的原文在文件里出现 %d 次，不唯一。\n"
                "  ⇒ 多带几行上下文，让它唯一" % cnt)

    out = src.replace(old, new, 1)

    # ---- 基础检查（按扩展名）----
    #
    # ★★★ 2026-10-02 修正：Verilog 的检查必须【先去掉注释和字符串】再数关键字。
    #   我第一版直接 out.count("module")，结果把注释里的 "// module scope_cap"
    #   也数进去了，于是"改动没通过检查"—— 假阳性，把好改动拦住了。
    #   （这是离线测试抓出来的：加 ext_valid 明明是合法改动，却被判成
    #     "module/endmodule 数量不等（2 vs 1）"。）
    warns = []
    ext = os.path.splitext(fp)[1].lower()
    if ext == ".tcl":
        clean = "\n".join(ln.split("#", 1)[0] for ln in out.split("\n"))
        for ch, name in (("{", "花括号"), ("(", "圆括号"), ("[", "方括号")):
            pair = {"{": "}", "(": ")", "[": "]"}[ch]
            if clean.count(ch) != clean.count(pair):
                warns.append("%s 不配平（%d vs %d）"
                             % (name, clean.count(ch), clean.count(pair)))
    elif ext in (".v", ".sv", ".vh"):
        clean = _strip_hdl_comments(out)
        nm = len(_re.findall(r"\bmodule\b", clean))
        ne = len(_re.findall(r"\bendmodule\b", clean))
        if nm != ne:
            warns.append("module/endmodule 数量不等（%d vs %d）" % (nm, ne))
        nb = len(_re.findall(r"\bbegin\b", clean))
        # ★ 注意：`\bend\b` 本来就【不匹配】"endmodule"
        #   （end 后面紧跟 m 是单词字符，没有词边界）。
        #   我第一版又减了一次 endmodule 的数量，导致 3 个 end 被算成 2，
        #   把合法的 Verilog 判成"不配平"。第二次假阳性，还是测试抓出来的。
        nend = len(_re.findall(r"\bend\b", clean))
        if nb != nend:
            warns.append("begin/end 数量不等（%d vs %d）" % (nb, nend))
    elif ext in (".py",):
        try:
            import ast as _ast
            _ast.parse(out)
        except SyntaxError as e:
            warns.append("Python 语法错: line %s: %s" % (e.lineno, e.msg))
    elif ext in (".json",):
        try:
            json.loads(out)
        except Exception as e:
            warns.append("JSON 解析失败: %s" % str(e)[:80])

    if warns:
        return ("★ 改动没通过基础检查，**已放弃，原文件未动**（没有备份，"
                "因为没写任何东西）：\n  - %s\n"
                "  ⇒ 修好再试" % "\n  - ".join(warns))

    # ---- ★ 备份（放在检查【之后】）----
    #
    # ★★★ 2026-10-02 两个修正（都是离线测试抓出来的）★★★
    #   ① 备份必须挪到语法检查【之后】。原来放在检查之前，于是：
    #      ① 改成功（备份=原文）→ ② 又试一个坏改动 → ② 在检查前也拿了备份，
    #      而它拿到的"备份"其实是 ① 改过之后的文件。
    #   ② 备份文件名必须加【唯一后缀】。原来只精确到秒
    #      （.bak_hdl_%Y%m%d_%H%M%S），同一秒内两次改动会撞名，后一个把前一个
    #      覆盖掉 —— 于是回滚报"成功"，恢复出来的却是错误内容。
    #      （现象很迷惑：回滚说成功、文件却还是改过的样子）
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = "%s.bak_hdl_%s_%04d" % (fp, ts, int(time.time() * 997) % 10000)
    try:
        _shutil.copy2(fp, bak)
    except Exception as e:
        return "★ 备份失败（%s），为安全起见中止（原文件未动）" % e

    # ---- 写入 ----
    try:
        with open(fp, "w", encoding="utf-8") as f:
            f.write(out)
    except Exception as e:
        return "写文件失败：%s（备份在 %s，可以手工恢复）" % (e, bak)

    # ---- 简单 diff ----
    diff = []
    for a1, b1 in zip(src.split("\n"), out.split("\n")):
        if a1 != b1:
            diff.append("  - %s" % a1.strip()[:120])
            diff.append("  + %s" % b1.strip()[:120])
            if len(diff) >= 10:
                break

    _add_change("hdl", "改 %s: %s" % (fp, note), "成功，备份 %s" % bak,
                extra={"backup": bak, "path": fp})
    return ("✓ 已改 %s\n  备份：%s\n  改动：\n%s\n\n"
            "★ 下一步：hw_fpga_build 让 PC 侧重新综合出流（如果要生效）\n"
            "★ 改坏了要回滚：用 hw_change_rollback（会优先用快照，"
            "没有快照就用这次记下的备份 %s）"
            % (fp, bak, "\n".join(diff) if diff else "  （内容变化很小）",
               os.path.basename(bak)))


def _hw_hdl_edit_DISABLED(a, ctx):
    """（保留旧定义的位置说明，实际实现已经合并到上面的 _hw_hdl_edit）"""
    return "unused"


@tool("hw_thermal_set",
      "调整温度守护的阈值。会改运行中的保护策略，需要用户批准。"
      "传哪一项就只改哪一项，不传的保持原值。",
      {"type": "object",
       "properties": {
           "warn": {"type": "number"},
           "cool": {"type": "number"},
           "stop": {"type": "number"},
           "emerg": {"type": "number", "description": "到达此温度会重启降温"},
       }})
def _hw_thermal_set(a, ctx):
    g = _policy_gate("write", "thermal thresholds %s" % a)
    if g:
        return g
    src = "/home/zynq/thermal_guard.py"
    if not os.path.exists(src):
        return "没找到 %s" % src
    txt = open(src).read()
    changed = []
    for key, const in (("warn", "T_WARN"), ("cool", "T_COOL"),
                       ("stop", "T_STOP"), ("emerg", "T_EMERG")):
        if a.get(key) is None:
            continue
        try:
            v = float(a[key])
        except Exception:
            return "错误：%s 要给数字" % key
        new = re.sub(r"^%s\s*=\s*[\d.]+" % const,
                     "%s = %.1f" % (const, v), txt, flags=re.M)
        if new != txt:
            txt = new
            changed.append("%s=%.1f" % (const, v))
    if not changed:
        return "没指定要改哪一项（warn/cool/stop/emerg）"
    bak = src + ".bak_thermalset_" + time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(src, bak)
    open(src, "w", encoding="utf-8").write(txt)
    _sh(["systemctl", "restart", "thermal-guard"], 30)
    _add_change("driver", "温度阈值改为 %s" % ", ".join(changed),
                "已重启守护，备份 %s" % bak)
    return ("已修改温度阈值：%s\n备份：%s\n守护已重启" %
            (", ".join(changed), bak))


@tool("hw_verify",
      "跑一遍硬件回归检查清单（桌面/音频/agent/自研IP/CNN地址/codec/帧缓冲/温度）。"
      "改完任何东西都应该跑一次。只读、安全。",
      {"type": "object", "properties": {}})
def _hw_verify(a, ctx):
    try:
        from . import hw_change as HC
    except Exception as e:
        return "加载 hw_change 失败：%s" % e
    try:
        passed, checks = HC.verify_all(verbose=False)
    except Exception as e:
        return "验证清单执行失败：%s: %s" % (type(e).__name__, e)
    lines = ["硬件回归检查清单："]
    for c in checks:
        tag = "硬" if c["hard"] else "软"
        mark = "✓" if c["ok"] else ("✗" if c["hard"] else "⚠")
        lines.append("  [%s] %s %-22s %s" % (tag, mark, c["name"], c["detail"]))
    lines.append("")
    lines.append("★ 结论：%s" % ("全部通过" if passed
                              else "硬检查有失败 —— 需要用 hw_change_rollback 回滚"))
    return "\n".join(lines)


@tool("hw_change_apply",
      "★★ 变更事务：改硬件（RTL/BD/驱动/配置）时走这个，不要直接改。"
      "它会：①记变更单 ②快照涉及的文件 ③执行 ④跑验证清单 ⑤失败自动回滚。"
      "这样改错了不会把板子留在坏状态。需要用户批准。",
      {"type": "object",
       "properties": {
           "kind": {"type": "string",
                    "description": "类型：bd / rtl / driver / config / other"},
           "detail": {"type": "string", "description": "改了什么、为什么"},
           "actions": {
               "type": "array",
               "description": "要执行的命令列表，按顺序跑；任一失败就整体回滚",
               "items": {
                   "type": "object",
                   "properties": {
                       "desc": {"type": "string"},
                       "cmd": {"type": "string"},
                   },
                   "required": ["cmd"],
               }},
           "paths": {
               "type": "array",
               "description": "涉及的文件路径（用于快照和回滚）",
               "items": {"type": "string"}},
           "skip_verify": {
               "type": "boolean",
               "description": "跳过自动验证（★ 不推荐，默认 false）"},
       },
       "required": ["kind", "detail", "actions"]})
def _hw_change_apply(a, ctx):
    g = _policy_gate("write", "hw_change_apply %s: %s"
                     % (a.get("kind"), str(a.get("detail"))[:120]))
    if g:
        return g
    try:
        from . import hw_change as HC
    except Exception as e:
        return "加载 hw_change 失败：%s" % e

    acts = a.get("actions") or []
    if not isinstance(acts, list) or not acts:
        return "错误：actions 要给一个非空列表，每项形如 {desc, cmd}"
    pairs = []
    for i, it in enumerate(acts):
        if isinstance(it, dict):
            cmd = it.get("cmd") or it.get("command") or ""
            pairs.append((it.get("desc") or "第%d步" % (i + 1), cmd))
        elif isinstance(it, str):
            pairs.append(("第%d步" % (i + 1), it))
    pairs = [(d, c) for d, c in pairs if c]
    if not pairs:
        return "错误：actions 里没有可执行的命令"

    paths = a.get("paths") or []
    if not isinstance(paths, list):
        paths = [str(paths)]

    try:
        ok, msg = HC.apply_change(
            str(a.get("kind"))[:40], str(a.get("detail"))[:400],
            pairs, [str(p) for p in paths],
            who="agent", skip_verify=bool(a.get("skip_verify")),
            verbose=False)
    except Exception as e:
        return "变更事务出错：%s: %s" % (type(e).__name__, e)
    return msg


@tool("hw_change_rollback",
      "把某一次变更回滚到快照状态。需要用户批准。用 hw_change_list 拿 id。",
      {"type": "object",
       "properties": {
           "id": {"type": "string", "description": "变更单 id"},
       },
       "required": ["id"]})
def _hw_change_rollback(a, ctx):
    cid = str(a.get("id", "")).strip()
    if not cid:
        return "错误：要指定变更单 id（用 hw_change_list 查）"
    g = _policy_gate("write", "hw_change_rollback %s" % cid)
    if g:
        return g
    try:
        from . import hw_change as HC
    except Exception as e:
        return "加载 hw_change 失败：%s" % e
    ok, why = HC.rollback(cid, verbose=False)
    _add_change("rollback", "回滚 %s" % cid,
                "成功" if ok else "失败: %s" % why)
    return "回滚 %s：%s\n%s" % (cid, "成功" if ok else "失败", why)


@tool("hw_waveform_classify",
      "波形识别：把一段波形（或示波器采的）转成时频图，送 PL 上的 CNN 分类。"
      "这是『示波器 + AI』那条线的入口。"
      "★ 现在 CNN 里装的还是 MNIST 权重，所以输出的是数字 0-9；"
      "等 AI 负责人给出波形分类权重后才是真正的波形类别。"
      "只读（读示波器 + 跑推理），安全。",
      {"type": "object",
       "properties": {
           "source": {"type": "string",
                      "description": "波形来源：scope(板上示波器) / "
                                     "synthetic(合成) / file(文件路径)"},
           "kind": {"type": "string",
                    "description": "source=synthetic 时的波形类型："
                                   "sine/square/triangle/sawtooth/pulse/"
                                   "am/fm/noise/flat/hum"},
           "freq": {"type": "number", "description": "合成波形的频率 Hz"},
           "file": {"type": "string", "description": "source=file 时的文件路径"},
           "show_image": {"type": "boolean",
                          "description": "是否把 28×28 时频图用字符画打印出来"},
           # ★ source=scope 时的采集参数
           "src": {"type": "integer",
                   "description": "0=内部 DDS（默认），1=外部 XADC"},
           "dec": {"type": "integer", "description": "抽取 1~255，默认 1"},
           "trig_level": {"type": "integer", "description": "触发电平 0~255"},
           "trig_edge": {"type": "integer", "description": "0=上升 1=下降"},
           "trig_mode": {"type": "integer",
                         "description": "0=Auto 1=Normal 2=Single"},
           # ★ 顺手设 DDS 自造信号（做数据集时很有用）
           "dds_wave": {"type": "integer",
                        "description": "0=正弦 1=方波 2=三角 3=锯齿"},
           "dds_freq": {"type": "number", "description": "DDS 频率 Hz"},
       }})
def _hw_waveform_classify(a, ctx):
    try:
        import sys as _sys
        if "/home/zynq" not in _sys.path:
            _sys.path.insert(0, "/home/zynq")
        import waveform_ai as W
    except Exception as e:
        return ("加载 waveform_ai 失败：%s\n"
                "（这个模块要在板子上：/home/zynq/waveform_ai.py）" % e)

    src = (a.get("source") or "synthetic").strip()
    lines = []

    # ---- ① 拿波形 ----
    if src == "synthetic":
        kind = (a.get("kind") or "sine").strip()
        if kind not in W.CLASS_NAMES:
            return ("错误：kind 要给 %s 之一" % "/".join(W.CLASS_NAMES))
        freq = float(a.get("freq") or 10000.0)
        w = W.gen_wave(kind, n=W.SCOPE_POINTS, freq=freq, seed=12345)
        lines.append("波形来源：合成 %s @ %.0f Hz（%d 点）" % (kind, freq, len(w)))
    elif src == "file":
        fp = a.get("file") or ""
        if not fp or not os.path.exists(fp):
            return "错误：找不到波形文件 %r" % fp
        raw = open(fp, "rb").read()
        import array as _arr
        w = _arr.array("f")
        for b in raw:
            w.append((b - 128) / 128.0)
        lines.append("波形来源：文件 %s（%d 字节）" % (fp, len(raw)))
    elif src == "scope":
        # ★★★ 2026-10-02 修正：原来这里跑 `python3 scope.py --raw` ——
        #   那个命令行参数根本不存在，所以这条路从来没走通过。
        #   现在改成调【接口 ③】的实现 scope_capture.capture_once()，
        #   它返回约定的 {ok, samples[4096], fs_hz, trig_pos, meta}。
        try:
            import scope_capture as SC
        except Exception:
            for p in ("/home/zynq", "/home/zynq/ui"):
                if p not in sys.path:
                    sys.path.insert(0, p)
            try:
                import scope_capture as SC
            except Exception as e:
                return ("加载 scope_capture 失败：%s\n"
                        "  （应该在 /home/zynq/scope_capture.py）" % e)

        # 可以在同一次调用里顺手设 DDS 自造信号
        if a.get("dds_wave") is not None and a.get("dds_freq") is not None:
            d = SC.set_dds(int(a["dds_wave"]), float(a["dds_freq"]))
            if not d.get("ok"):
                return "设 DDS 失败：%s" % d["error"]
            lines.append("已设 DDS：波形 %d @ %.1f Hz"
                         % (d["waveform"], d["freq_hz"]))

        r = SC.capture_once(
            src=_safe_int(a.get("src"), 0, 0, 1),
            dec=_safe_int(a.get("dec"), 1, 1, 255),
            trig_level=_safe_int(a.get("trig_level"), 128, 0, 255),
            trig_edge=_safe_int(a.get("trig_edge"), 0, 0, 1),
            trig_mode=_safe_int(a.get("trig_mode"), 0, 0, 2))
        if not r.get("ok"):
            return ("★ 没能从示波器拿到数据：%s\n"
                    "  先确认：① bitstream 刷了没 ② scope_0 @0x43CC0000 在不在"
                    "（hw_reg_read base=scope_0 offset=0x34，应得 0x53434F50）\n"
                    "  或者先用 source=synthetic 验证这条链本身是通的。"
                    % r.get("error"))
        # ★ 8 位样本 -> [-1, 1] 浮点（waveform_ai 要的格式）
        #   128 是中点；除以 128 归一化
        w = [(int(v) - 128) / 128.0 for v in r["samples"]]
        lines.append("波形来源：板上示波器（%d 点，采样率 %.0f Hz，源 %s）"
                     % (len(w), r["fs_hz"], (r.get("meta") or {}).get("src", "?")))
        lines.append("示波器粗测：Vpp %s，占空比 %s，频率 %s Hz"
                     % ((r.get("meta") or {}).get("vpp"),
                        (r.get("meta") or {}).get("duty"),
                        (r.get("meta") or {}).get("freq_hz")))
    else:
        return "错误：source 要给 scope / synthetic / file"

    # ---- ② 转时频图 ----
    img = W.waveform_to_image(w)
    s = W.image_summary(img)
    lines.append("时频图：28×28，均值 %.1f，非零 %d/%d"
                 % (s["mean"], s["nonzero"], len(img)))
    if a.get("show_image"):
        lines.append("")
        lines.append(s["art"])

    # ---- ③ 送 CNN ----
    cls, info = W.classify_with_cnn(img, cnn_script="/home/zynq/cnn_linux.py")
    lines.append("")
    if cls is None:
        lines.append("CNN 推理：%s" % info)
        lines.append("")
        lines.append("★ 但这条链的【预处理部分】是通的 —— 时频图已经生成好了。")
        lines.append("  等 AI 负责人给出波形分类权重后，把权重换掉就能直接出类别。")
    else:
        name = W.CLASS_NAMES[cls] if 0 <= cls < len(W.CLASS_NAMES) else "?"
        lines.append("CNN 推理：类别 %d (%s)" % (cls, name))
    return "\n".join(lines)


@tool("hw_waveform_dataset",
      "生成波形分类的训练数据集（给 AI 负责人用）。"
      "★ 关键：这份数据集的预处理（STFT + 量化）和推理时完全一致，"
      "所以模型在 PC 上训完，上板就能直接用。会写盘，需要批准。",
      {"type": "object",
       "properties": {
           "per_class": {"type": "integer",
                         "description": "每类生成多少张，默认 200"},
           "out": {"type": "string",
                   "description": "输出目录，默认 /home/zynq/wave_dataset"},
       }})
def _hw_waveform_dataset(a, ctx):
    g = _policy_gate("write", "generate waveform dataset")
    if g:
        return g
    try:
        import sys as _sys
        if "/home/zynq" not in _sys.path:
            _sys.path.insert(0, "/home/zynq")
        import waveform_ai as W
    except Exception as e:
        return "加载 waveform_ai 失败：%s" % e
    per = _safe_int(a.get("per_class"), 200, 1, 5000)
    out = a.get("out") or "/home/zynq/wave_dataset"
    try:
        n = W.make_dataset(per, out)
    except Exception as e:
        return "生成失败：%s: %s" % (type(e).__name__, e)
    _add_change("dataset", "生成波形数据集 %d 张 -> %s" % (n, out), "成功")
    return ("已生成 %d 张（%d 类 × %d）\n目录：%s\n"
            "文件：images.bin / labels.bin / meta.json\n"
            "★ 训练时必须用同一套预处理（meta.json 里写了参数）。"
            % (n, len(W.CLASSES), per, out))


# ---------------------------------------------------------------- 注册完成
def loaded():
    """返回本模块注册了哪些工具（方便自检）"""
    return sorted(n for n in REGISTRY if n.startswith("hw_"))
