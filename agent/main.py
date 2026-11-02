#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py —— 板载 Agent 入口

三种用法：
  python -m agent.main "任务"              单次执行（命令行）
  python -m agent.main -i                  交互式
  python -m agent.main --serve             起 HTTP 服务（给 ESP32 和桌面用）
          POST /voice  {"text": "..."}   ->  {"reply": "...", "rounds": n}
          GET  /health                   ->  {"ok": true, ...}

HTTP 服务只用标准库（http.server），板子上不用装任何依赖。
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.core import Agent, Session      # noqa: E402
from agent import config                   # noqa: E402
from agent import llm, tools               # noqa: E402

PORT = 8765


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "XiaoBai/0.1"
    agent = None
    lock = threading.Lock()

    def log_message(self, fmt, *a):
        print("[http] " + (fmt % a))

    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


    # ══════════════════════════════════════════════════════════
    #  辅助：访问音频服务 / 取状态
    # ══════════════════════════════════════════════════════════
    AUDIO = os.environ.get("AUDIO_SVC", "http://127.0.0.1:8767")

    def _audio(self, path, data=None, timeout=180):
        """调音频服务（8767）。板子上的 SSL 证书链不全，统一走不校验。"""
        import ssl
        import urllib.request
        url = Handler.AUDIO + path
        if data is None:
            req = urllib.request.Request(url)
        else:
            req = urllib.request.Request(
                url, data=json.dumps(data).encode(),
                headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(
                req, timeout=timeout,
                context=ssl._create_unverified_context()) as r:
            body = r.read()
        try:
            return json.loads(body.decode("utf-8", "replace"))
        except Exception:
            return {"ok": True, "raw_len": len(body)}

    @staticmethod
    def _svc(name):
        """服务是否 active"""
        try:
            import subprocess
            o = subprocess.run(["systemctl", "is-active", name],
                               stdout=subprocess.PIPE, timeout=6)
            return o.stdout.decode().strip()
        except Exception:
            return "?"

    @staticmethod
    def _sysinfo():
        d = {}
        try:
            for line in open("/proc/meminfo"):
                k, v = line.split(":", 1)
                if k in ("MemTotal", "MemAvailable"):
                    d[k] = int(v.strip().split()[0]) // 1024
        except Exception:
            pass
        # ★ 温度：这块板子**没有 thermal_zone**，只有 XADC。
        #   优先用 IIO 的标准属性 (raw + offset) * scale（scale 单位是毫度）。
        #   踩过的坑：原来写"raw > 2000 就 /1000"（那是给 millidegree 格式的），
        #   而 XADC 的 raw 也是四位数（2886），被误判成 2.9 °C。
        _xd = "/sys/devices/soc0/amba/f8007100.adc/iio:device0"
        try:
            _r = float(open(_xd + "/in_temp0_raw").read())
            _o = float(open(_xd + "/in_temp0_offset").read())
            _s = float(open(_xd + "/in_temp0_scale").read())
            d["temp"] = round((_r + _o) * _s / 1000.0, 1)
            d["temp_src"] = "xadc"
        except Exception:
            for p in ("/sys/class/thermal/thermal_zone0/temp",
                      "/sys/class/hwmon/hwmon0/temp1_input"):
                try:
                    raw = int(open(p).read().strip())
                    d["temp"] = round(raw / 1000.0, 1)
                    d["temp_src"] = p.split("/")[-2]
                    break
                except Exception:
                    continue
        try:
            d["load"] = open("/proc/loadavg").read().split()[0]
        except Exception:
            pass
        try:
            import subprocess
            d["uptime"] = subprocess.run(["uptime", "-p"],
                                         stdout=subprocess.PIPE,
                                         timeout=6).stdout.decode().strip()
        except Exception:
            pass
        return d

    def _api_status(self):
        st = {
            "ok": True,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "services": {"zynq-agent": self._svc("zynq-agent"),
                         "zynq-audio": self._svc("zynq-audio"),
                         "zynq-desktop": self._svc("zynq-desktop")},
            "system": self._sysinfo(),
        }
        try:
            st["audio"] = self._audio("/state", timeout=8)
        except Exception as e:
            st["audio"] = {"error": str(e)[:120]}
        try:
            from . import asr as _asr
            st["asr"] = {"vosk": _asr.vosk_available()}
        except Exception:
            st["asr"] = {}
        try:
            from . import tts as _tts
            st["tts"] = {"espeak": os.path.exists(_tts.ESPEAK),
                         "baidu_keys": bool(_tts._keys()[0]
                                            and _tts._keys()[1])}
        except Exception:
            st["tts"] = {}
        return st

    def _api_tools(self):
        """工具清单。★ 条目是 dict：{"name","desc","params","fn"}"""
        out = []
        for name, t in sorted(tools.REGISTRY.items()):
            desc = ""
            params = None
            if isinstance(t, dict):
                desc = t.get("desc") or ""
                params = t.get("params")
                if not desc:
                    fn = t.get("fn")
                    d = getattr(fn, "__doc__", None)
                    if isinstance(d, str):
                        desc = d
            else:
                desc = getattr(t, "desc", "") or ""
            desc = (desc or "").strip().splitlines()[0][:180] if desc else ""
            item = {"name": name, "description": desc}
            if params:
                try:
                    props = params.get("properties") or {}
                    item["params"] = sorted(props.keys())
                    item["required"] = params.get("required") or []
                except Exception:
                    pass
            out.append(item)
        return {"ok": True, "count": len(out), "tools": out}

    API_DOC = [
        ("GET", "/", "本清单"),
        ("GET", "/health", "服务健康 + 工具名列表"),
        ("GET", "/status", "完整状态（三个服务 + 音频 + 温度/内存）"),
        ("GET", "/tools", "工具清单 + 说明"),
        ("GET", "/audio/state", "音频服务状态"),
        ("GET", "/history", "对话历史"),
        ("POST", "/voice 或 /chat", '{"text":"..."} 对话'),
        ("POST", "/intent", '{"text":..,"system":..} 无状态意图（ESP32 用）'),
        ("POST", "/tool", '{"name":..,"args":{..}} 直接调工具'),
        ("POST", "/asr", '{"audio":"<base64 wav>"} 或 {"file":"/x.wav"} -> 文字'),
        ("POST", "/tts", '{"text":"..."} -> {"audio":"<base64 wav>"}'),
        ("POST", "/say", '{"text":"..."} 合成并从喇叭放出来'),
        ("POST", "/audio", '{"action":"play|stop|volume|record|state", ...}'),
        ("POST", "/session", '{"action":"reset"} 清空会话'),
        ("GET", "/pending", "待批准的危险动作 + 权限层状态"),
        ("POST", "/approve", '{"id":"..","ok":true} 同意/拒绝（id=all 全部）'),
        ("POST", "/pending/clear", "清空待批准队列"),
        ("GET/POST", "/llm/config",
         '{"mode":"local|cloud|auto"} 切推理模式（不传则查询）'),
    ]

    def do_GET(self):
        p = self.path.split("?")[0]

        if p in ("/", "/api", "/help"):
            self._send(200, {"ok": True, "service": "系统管家小白",
                             "port": PORT,
                             "endpoints": [{"method": m, "path": a, "desc": d}
                                           for m, a, d in self.API_DOC]})
            return

        if p.startswith("/health"):
            cfg = config.load(reload=True)     # ★ reload：客户端改完立刻反映
            self._send(200, {
                "ok": True, "model": cfg["model"],
                "tools": list(tools.REGISTRY.keys()),
                "has_key": bool(cfg["api_key"]),
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            return

        # ★ 查询当前 LLM 配置（POST 是改，GET 是读）
        #   PC 客户端"打开设置"时要回显当前 model / api_base / 有没有 key
        if p.startswith("/llm/settings") or p.startswith("/settings"):
            try:
                c = config.load(reload=True)
                self._send(200, {"ok": True,
                                 "model": c.get("model"),
                                 "api_base": c.get("api_base"),
                                 "has_key": bool(c.get("api_key")),
                                 "voice_reply": c.get("voice_reply"),
                                 "voice_auto_send": c.get("voice_auto_send"),
                                 "file": config.OVERRIDE})
            except Exception as e:
                self._send(500, {"error": "%s: %s" % (type(e).__name__, e)})
            return

        # ★ 查询当前推理模式（POST /llm/config 是切换，GET 是查询）
        if p.startswith("/llm/config"):
            MODE_FILE = "/home/zynq/.agent_mode"
            try:
                with open(MODE_FILE, encoding="utf-8") as f:
                    m = f.read().strip().lower()
            except Exception:
                m = "auto"
            if m not in ("local", "cloud", "auto"):
                m = "auto"
            self._send(200, {"ok": True, "mode": m, "file": MODE_FILE,
                             "valid": ["local", "cloud", "auto"]})
            return

        # ★ 可选模型列表（客户端"模型切换"下拉用）
        if p.startswith("/llm/models") or p.startswith("/models"):
            try:
                from . import llm as _llm
                c = config.load(reload=True)
                cur = c.get("model")
                raw = None
                try:
                    raw = _llm.models(c)
                except Exception as e:
                    self._send(200, {"ok": False,
                                     "error": "%s: %s" % (type(e).__name__, e),
                                     "models": [cur] if cur else [],
                                     "current": cur})
                    return

                # ★★ 解析千万别想当然（踩过）：
                #   llm.models() 返回的是【整个 API 响应】：
                #       {"object": "list", "data": [{"id": "deepseek-flash", ...}, ...]}
                #   我第一版直接 `for m in raw` —— 那是在遍历 dict 的【键】，
                #   于是模型列表变成了 ["deepseek-chat", "object", "data"]，
                #   前端的下拉框里就出现 "object" 和 "data" 两个假模型。
                #   ⇒ 必须在 data 里取 id。
                ids = []
                if isinstance(raw, dict):
                    arr = raw.get("data") or raw.get("models") or []
                elif isinstance(raw, list):
                    arr = raw
                else:
                    arr = []
                for m in arr:
                    if isinstance(m, dict):
                        v = m.get("id") or m.get("name") or m.get("model")
                    else:
                        v = str(m)
                    if v and v not in ids:
                        ids.append(v)
                if cur and cur not in ids:
                    ids.insert(0, cur)
                # ★★★ 合并【用户自己添加的模型】（2026-10-03）
                #   用户："能添加模型吗？"
                #   官方 /models 只给那几个，所以要允许自己加。
                #   存在覆盖文件的 extra_models 里（字符串列表）。
                for m in (c.get("extra_models") or []):
                    m = str(m).strip()
                    if m and m not in ids:
                        ids.append(m)
                # ★★★ 把【本地】也列进去（用户问：怎么只有 deepseek 两个？）
                #
                # 说明：本地的不是"DeepSeek 的一个模型"，而是
                #   Tier 1 的【离线 RAG】（536+7 个知识块，纯标准库 BM25）。
                #   它不是 LLM，所以没法从 /models 拉出来 —— 但界面上
                #   必须能看到、能选，不然用户以为"本地模型没做"。
                #   选中它 = 把模式切成 local。
                LOCAL_TAG = "本地（离线 RAG）"
                if LOCAL_TAG not in ids:
                    ids.append(LOCAL_TAG)
                self._send(200, {"ok": bool(ids), "models": ids, "current": cur,
                                 "api_base": c.get("api_base"),
                                 "local_tag": LOCAL_TAG})
            except Exception as e:
                self._send(500, {"error": "%s: %s" % (type(e).__name__, e)})
            return

        if p.startswith("/status"):
            try:
                self._send(200, self._api_status())
            except Exception as e:
                self._send(500, {"error": str(e)[:200]})
            return

        if p.startswith("/tools"):
            try:
                self._send(200, self._api_tools())
            except Exception as e:
                self._send(500, {"error": str(e)[:200]})
            return

        if p.startswith("/audio/state") or p == "/audio":
            try:
                self._send(200, self._audio("/state", timeout=10))
            except Exception as e:
                self._send(502, {"error": "音频服务不可用: %s" % str(e)[:150]})
            return

        if p.startswith("/pending"):
            try:
                from . import policy
                self._send(200, {"ok": True, "policy": policy.describe(),
                                 "pending": policy.list_pending()})
            except Exception as e:
                self._send(500, {"error": str(e)[:200]})
            return

        if p.startswith("/history"):
            a = Handler.agent
            try:
                msgs = getattr(getattr(a, "session", None), "messages", [])
                self._send(200, {"ok": True, "count": len(msgs),
                                 "messages": msgs[-40:]})
            except Exception as e:
                self._send(500, {"error": str(e)[:200]})
            return

        self._send(404, {"error": "not found", "hint": "GET / 看接口清单"})

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n).decode("utf-8", "replace") if n else "{}"
            data = json.loads(raw or "{}")
        except Exception as e:
            self._send(400, {"error": "bad json: %s" % e})
            return

        if self.path.startswith("/voice") or self.path.startswith("/chat"):
            text = (data.get("text") or data.get("message") or "").strip()
            if not text:
                self._send(400, {"error": "text 为空"})
                return
            # ★★★ 共享对话记录（2026-10-03）
            #   用户报："对话和板子不一致，没同步啊"
            #   根因：板载 UI 和 PC 客户端调的是同一个 /voice，
            #         但各自记各自的账（板载 UI 写 .agent_chats.json，
            #         PC 端写自己本地的），所以永远对不上。
            #   ⇒ 现在由 agent 负责把这一轮问答写进【板载 UI 那个文件】，
            #      这样板载 UI 下次启动就能读到 PC 发的对话，反之亦然。
            #   ★ source="ui" 时跳过：板载 UI 自己会 save_sessions()，
            #     这里再记就重复了。
            _src = str(data.get("source") or "pc").lower()
            # 串行执行（板上资源有限，也是为了让语音一问一答有序）
            with Handler.lock:
                a = Agent(verbose=True)
                t0 = time.time()
                reply, meta = a.run(text)
            try:
                from . import shared_chat as _sc
                _sc.append(text, reply, source=_src)
            except Exception as _e:
                print("  [shared_chat] 记录失败（不影响回答）: %s" % _e)
            self._send(200, {"reply": reply, "rounds": meta.get("rounds"),
                             "elapsed": round(time.time() - t0, 2)})
            return

        if self.path.startswith("/asr"):
            # 音频 -> 文字。两种用法：给 base64，或给板子上的文件路径
            import base64 as _b64
            wav = data.get("file") or "/tmp/xiaobai_asr_in.wav"
            if data.get("audio"):
                try:
                    open(wav, "wb").write(_b64.b64decode(data["audio"]))
                except Exception as e:
                    self._send(400, {"error": "base64 解不开: %s" % e})
                    return
            try:
                from . import asr as _asr
                with Handler.lock:
                    t0 = time.time()
                    text, engine = _asr.recognize(
                        wav, rate=int(data.get("rate") or 16000),
                        engine=data.get("engine"))
                self._send(200, {"ok": True, "text": text, "engine": engine,
                                 "elapsed": round(time.time() - t0, 2)})
            except Exception as e:
                self._send(500, {"error": str(e)[:250]})
            return

        if self.path.startswith("/tts"):
            text = (data.get("text") or "").strip()
            if not text:
                self._send(400, {"error": "text 为空"})
                return
            try:
                import base64 as _b64
                from . import tts as _tts
                out = data.get("file") or "/tmp/xiaobai_tts_out.wav"
                p2 = _tts.synth(text, out_path=out,
                                per=int(data.get("per") or 0),
                                vol=int(data.get("vol") or 15),
                                engine=data.get("engine"))
                raw = open(p2, "rb").read()
                self._send(200, {"ok": True, "path": p2, "bytes": len(raw),
                                 "audio": _b64.b64encode(raw).decode()})
            except Exception as e:
                self._send(500, {"error": str(e)[:250]})
            return

        if self.path.startswith("/say"):
            # 合成 + 从喇叭放出来
            text = (data.get("text") or "").strip()
            if not text:
                self._send(400, {"error": "text 为空"})
                return
            try:
                from . import tts as _tts
                p2 = _tts.synth(text, out_path="/tmp/xiaobai_say.wav",
                                per=int(data.get("per") or 0),
                                vol=int(data.get("vol") or 15))
                r = self._audio("/play", {"file": p2}, timeout=120)
                self._send(200, {"ok": True, "path": p2, "audio_service": r})
            except Exception as e:
                self._send(500, {"error": str(e)[:250]})
            return

        if self.path.startswith("/audio") and not self.path.startswith(
                "/audio/state"):
            act = (data.get("action") or "").lower()
            try:
                if act == "play":
                    r = self._audio("/play", {"file": data.get("file"),
                                              "tone": data.get("tone"),
                                              "secs": data.get("secs"),
                                              "amp": data.get("amp")},
                                    timeout=180)
                elif act == "stop":
                    r = self._audio("/stop", {}, timeout=20)
                elif act == "volume":
                    r = self._audio("/volume", {"v": data.get("v")}, timeout=20)
                elif act == "record":
                    r = self._audio("/record",
                                    {"secs": data.get("secs") or 3,
                                     "rate": data.get("rate") or 16000,
                                     "mono": True}, timeout=240)
                    if isinstance(r, dict) and data.get("file"):
                        pass
                elif act in ("state", "", None):
                    r = self._audio("/state", timeout=10)
                else:
                    self._send(400, {"error": "未知 action: %s" % act})
                    return
                self._send(200, {"ok": True, "action": act, "result": r})
            except Exception as e:
                self._send(502, {"error": str(e)[:250]})
            return

        if self.path.startswith("/approve"):
            try:
                from . import policy
                rid = data.get("id")
                ok = bool(data.get("ok", True))
                if rid in (None, "", "all"):
                    items = policy.list_pending()
                    n = 0
                    for it in items:
                        if policy.resolve(it["id"], ok):
                            n += 1
                    self._send(200, {"ok": True, "resolved": n, "approve": ok})
                    return
                it = policy.resolve(rid, ok)
                if it is None:
                    self._send(404, {"error": "没有这个待批准动作: %s" % rid})
                    return
                self._send(200, {"ok": True, "resolved": it, "approve": ok})
            except Exception as e:
                self._send(500, {"error": str(e)[:200]})
            return

        if self.path.startswith("/pending/clear"):
            try:
                from . import policy
                n = policy.clear_pending()
                self._send(200, {"ok": True, "cleared": n})
            except Exception as e:
                self._send(500, {"error": str(e)[:200]})
            return

        if self.path.startswith("/session"):
            act = (data.get("action") or "reset").lower()
            if act in ("reset", "clear", "new"):
                try:
                    Handler.agent.session.reset()
                except Exception:
                    Handler.agent.session = None
                self._send(200, {"ok": True, "action": act})
            else:
                self._send(400, {"error": "未知 action: %s" % act})
            return

        # ══════════════════════════════════════════════════════════
        #  ★★ 模型配置（2026-10-02 加）—— 让客户端能"切换模型"
        # ══════════════════════════════════════════════════════════
        # 为什么要有这两个端点：
        #   原来模型是 systemd 用环境变量 AGENT_MODEL 注入的，
        #   只在进程启动时读一次 —— 客户端想切模型只能重启 agent。
        #   现在 config.py 多了一层【运行时覆盖文件】
        #   （/home/zynq/.agent_settings.json，优先级最高），
        #   这两个端点负责读写它，改完【立刻生效】。
        if self.path.startswith("/llm/model") or self.path.startswith("/model"):
            from . import config as _cfg
            m = (data.get("model") or "").strip()
            if not m:
                self._send(400, {"error": "要给 model"})
                return
            # ══════════════════════════════════════════════════════
            #  ★★★ 「本地（离线 RAG）」是个【模式】，不是模型名
            #  （2026-10-03 修）★★★
            #
            #  踩过：/llm/models 会把 "本地（离线 RAG）" 列进模型列表
            #  （这是故意的 —— 界面上得能看到"本地"这个选项）。
            #  但这里原来【无脑】save_override({"model": m})，
            #  于是选中"本地"之后：
            #      · 模型名被写成中文标签 "本地（离线 RAG）"
            #      · 云端调用带着这个假模型名 -> 上游必然报错
            #      · ★ 而且模式【根本没切】到 local
            #  表现就是用户说的"本地模型也不行"，而且连云端也被搞坏了。
            #  ⇒ 这是典型的【假成功】：返回 ok=true，其实什么都没对。
            #
            #  正确做法：这个 tag 要翻译成"把模式切成 local"，
            #            并且【不要】动 model 字段。
            # ══════════════════════════════════════════════════════
            LOCAL_TAGS = ("本地（离线 RAG）", "本地（离线）", "本地", "local")
            MODE_FILE = "/home/zynq/.agent_mode"

            def _write_mode(mv):
                try:
                    tmp = MODE_FILE + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        f.write(mv + "\n")
                    os.replace(tmp, MODE_FILE)
                    try:
                        os.chmod(MODE_FILE, 0o644)
                    except Exception:
                        pass
                    return True
                except Exception:
                    return False

            if m in LOCAL_TAGS:
                if not _write_mode("local"):
                    self._send(500, {"error": "写不了 %s（权限？）" % MODE_FILE})
                    return
                c = _cfg.load(reload=True)
                self._send(200, {
                    "ok": True, "mode": "local",
                    "model": c.get("model"),          # ★ 模型名保持不动
                    "file": MODE_FILE,
                    "note": "「本地」是推理模式，不是模型名 —— 已切到 local",
                    "effect": "立刻生效（下次对话走本地 RAG）"})
                return
            try:
                _cfg.save_override({"model": m})
                # ★ 选了一个真模型 -> 顺便把模式切回 auto
                #   （不然用户之前选了"本地"，再选模型还是 local 模式，
                #     会以为切模型没生效）
                _write_mode("auto")
                c = _cfg.load(reload=True)      # ★ 立刻重载
                self._send(200, {"ok": True, "model": c.get("model"),
                                 "mode": "auto",
                                 "file": _cfg.OVERRIDE,
                                 "effect": "立刻生效（下次对话就用新模型）"})
            except Exception as e:
                self._send(500, {"error": "%s: %s" % (type(e).__name__, e)})
            return

        # ══════════════════════════════════════════════════════════
        #  ★★★ /llm/config —— 切推理模式（local / cloud / auto）
        # ══════════════════════════════════════════════════════════
        # 用户报："为什么切模式一直失败"
        #
        # 根因：板载 App 往 AGENT_URL(8765) + "/llm/config" 发请求，
        #       但【这个路由只存在于 cloud_api.py(8768)】，
        #       agent/main.py 里根本没有 ⇒ 404 ⇒ "切模式失败"。
        #
        # 现在补上，写法和 cloud_api.py 里那个保持一致：
        #   · 落到 /home/zynq/.agent_mode（和 agent/tiers.py 的常量一致）
        #   · 写临时文件再 os.replace，避免读到写了一半的内容
        #   · Tiers.mode 是动态属性，所以【立刻生效，不用重启】
        # ══════════════════════════════════════════════════════════
        if self.path.startswith("/llm/config"):
            MODE_FILE = "/home/zynq/.agent_mode"
            VALID = ("local", "cloud", "auto")

            def _read_mode():
                try:
                    with open(MODE_FILE, encoding="utf-8") as f:
                        m = f.read().strip().lower()
                    if m in VALID:
                        return m
                except Exception:
                    pass
                return "auto"

            try:
                want = (data.get("mode") or "").strip().lower()
                if not want:
                    self._send(200, {"ok": True, "mode": _read_mode(),
                                     "file": MODE_FILE,
                                     "valid": list(VALID)})
                    return
                if want not in VALID:
                    self._send(400, {"error": "mode 只能是 %s 之一"
                                              % "/".join(VALID)})
                    return
                tmp = MODE_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(want + "\n")
                os.replace(tmp, MODE_FILE)
                try:
                    os.chmod(MODE_FILE, 0o644)
                except Exception:
                    pass
                # ★ 让当前进程里的 Tiers 立刻跟着变（它是动态属性，会自动读）
                self._send(200, {"ok": True, "mode": _read_mode(),
                                 "file": MODE_FILE,
                                 "effect": "立刻生效（下次对话就走新模式）"})
            except Exception as e:
                self._send(500, {"error": "%s: %s" % (type(e).__name__, e)})
            return

        if self.path.startswith("/llm/settings") or self.path.startswith("/settings"):
            from . import config as _cfg
            try:
                # 只接受白名单里的键（config.save_override 里再过滤一次）
                patch = {}
                for k in ("model", "api_base", "api_key",
                          "voice_reply", "voice_auto_send",
                          "extra_models"):
                    if k in data and data[k] is not None:
                        patch[k] = data[k]
                if not patch:
                    _self = _cfg.load(reload=True)
                    self._send(200, {"ok": True,
                                     "model": _self.get("model"),
                                     "api_base": _self.get("api_base"),
                                     "has_key": bool(_self.get("api_key")),
                                     "voice_reply": _self.get("voice_reply"),
                                     "voice_auto_send": _self.get(
                                         "voice_auto_send"),
                                     "file": _cfg.OVERRIDE})
                    return
                _cfg.save_override(patch)
                c = _cfg.load(reload=True)
                self._send(200, {"ok": True,
                                 "model": c.get("model"),
                                 "api_base": c.get("api_base"),
                                 "has_key": bool(c.get("api_key")),
                                 "file": _cfg.OVERRIDE,
                                 "effect": "立刻生效"})
            except Exception as e:
                self._send(500, {"error": "%s: %s" % (type(e).__name__, e)})
            return

        if self.path.startswith("/intent"):
            # 给 ESP32 用的「无状态、不带工具」的模型调用：
            #   前端自带 system 提示词（要求只回 JSON），板子只负责调模型。
            #   回报 OpenAI 形状（choices[].message.content），
            #   这样 ESP32 那边原来解析 "content" 的代码一行都不用改。
            text = (data.get("text") or data.get("message") or "").strip()
            if not text:
                self._send(400, {"error": "text 为空"})
                return
            sysp = data.get("system") or (
                "你是一个嵌入式语音助手。只回 JSON，不要多余文字。")
            with Handler.lock:
                st = bool(data.get("stateless"))
                a = Agent(verbose=False,
                          session=(Session(name="_intent", cfg=config.load(),
                                           persist=False) if st else None))
                t0 = time.time()
                reply, meta = a.run(text, system=sysp,
                                    use_tools=bool(data.get("tools", False)))
            raw = reply or ""
            self._send(200, {
                "choices": [{"message": {"role": "assistant", "content": raw}}],
                "reply": raw,
                "rounds": meta.get("rounds"),
                "elapsed": round(time.time() - t0, 2),
            })
            return

        if self.path.startswith("/tool"):
            name = data.get("name")
            r = tools.call(name, data.get("args") or {}, {})
            self._send(200, {"result": r})
            return

        self._send(404, {"error": "not found"})


def serve(port=PORT):
    cfg = config.load()
    print("=" * 60)
    print(" 系统管家小白 · HTTP 服务")
    print(" 端口 %d   模型 %s   key %s" % (port, cfg["model"],
                                          "已配置" if cfg["api_key"] else "**缺失**"))
    print(" 工具: %s" % ", ".join(tools.REGISTRY.keys()))
    print(" 接口: POST /voice {\"text\":\"...\"}   GET /health")
    print("=" * 60)
    if not cfg["api_key"]:
        print("!! 没有 API key：设置环境变量 DEEPSEEK_API_KEY 再启动")
    Handler.agent = True
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n停下")


# ---------------------------------------------------------------- CLI
def main():
    args = [a for a in sys.argv[1:]]
    cfg = config.load()

    if "--models" in args:
        print(json.dumps(llm.models(cfg), ensure_ascii=False)[:800])
        return
    if "--tools" in args:
        for n, t in tools.REGISTRY.items():
            print("%-10s %s" % (n, t["desc"].split("\n")[0]))
        return
    if "--serve" in args:
        i = args.index("--serve")
        port = PORT
        if len(args) > i + 1 and args[i + 1].isdigit():
            port = int(args[i + 1])
        serve(port)
        return

    if "-i" in args:
        a = Agent()
        print("系统管家小白 · 交互模式（Ctrl-C 退出；输入 exit 结束）")
        while True:
            try:
                s = input("\n你> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not s or s in ("exit", "quit"):
                break
            ans, meta = a.run(s)
            print("\nAgent> " + ans)
        return

    task = " ".join(args)
    if not task:
        print(__doc__)
        return
    a = Agent()
    t0 = time.time()
    ans, meta = a.run(task)
    print("\n" + "=" * 60)
    print(ans)
    print("=" * 60)
    print("( %.1fs, %s 轮, session=%s )" % (time.time() - t0,
                                            meta.get("rounds"), a.session.name))


if __name__ == "__main__":
    main()
