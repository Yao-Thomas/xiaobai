#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_agent_api.py —— 给板载 Agent 补一套完整的 HTTP API

原来只有 4 个：
    GET  /health      服务健康
    POST /voice|/chat 对话
    POST /intent      意图（给 ESP32 用）
    POST /tool        调工具

补上这些（让 Agent 真正成为一个"服务"，桌面 UI / 手机 / 脚本都能驱动）：

    GET  /                接口清单（自动发现）
    GET  /status          完整系统状态（服务/音频/温度/内存/时间）
    GET  /tools           工具清单 + 说明
    GET  /audio/state     音频服务状态
    GET  /history         对话历史
    POST /asr             音频(base64 或文件路径) -> 文字   ★ 百度优先
    POST /tts             文字 -> 音频(base64)              ★ 百度 TTS vol=15
    POST /say             文字 -> 合成 + 从喇叭放出来        （便捷）
    POST /audio           控制音频：play/stop/volume/record
    POST /session         新建/清空会话
"""
import io
import sys

P = "agent/main.py"
src = io.open(P, encoding="utf-8").read()

if "/status" in src and "def _api_status" in src:
    print("已经打过补丁，跳过")
    sys.exit(0)

# ─────────────────────────────────────────── 辅助方法（插在 _send 之后）
HELPERS = '''
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
        for p in ("/sys/class/thermal/thermal_zone0/temp",):
            try:
                d["temp"] = round(int(open(p).read().strip()) / 1000.0, 1)
            except Exception:
                pass
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
        out = []
        for name, t in sorted(tools.REGISTRY.items()):
            desc = ""
            for attr in ("description", "desc", "__doc__"):
                v = getattr(t, attr, None)
                if isinstance(v, str) and v.strip():
                    desc = v.strip().splitlines()[0][:160]
                    break
            if not desc and isinstance(t, dict):
                desc = str(t.get("description") or t.get("desc") or "")[:160]
            out.append({"name": name, "description": desc})
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
    ]

'''
src = src.replace("    def do_GET(self):", HELPERS + "    def do_GET(self):", 1)

# ─────────────────────────────────────────── GET 分支
OLD_GET = '''    def do_GET(self):
        if self.path.startswith("/health"):
            cfg = config.load()
            self._send(200, {
                "ok": True, "model": cfg["model"],
                "tools": list(tools.REGISTRY.keys()),
                "has_key": bool(cfg["api_key"]),
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            return
        self._send(404, {"error": "not found"})
'''
NEW_GET = '''    def do_GET(self):
        p = self.path.split("?")[0]

        if p in ("/", "/api", "/help"):
            self._send(200, {"ok": True, "service": "系统管家小白",
                             "port": PORT,
                             "endpoints": [{"method": m, "path": a, "desc": d}
                                           for m, a, d in self.API_DOC]})
            return

        if p.startswith("/health"):
            cfg = config.load()
            self._send(200, {
                "ok": True, "model": cfg["model"],
                "tools": list(tools.REGISTRY.keys()),
                "has_key": bool(cfg["api_key"]),
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
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
'''
assert OLD_GET in src, "GET 锚点没找到"
src = src.replace(OLD_GET, NEW_GET, 1)

# ─────────────────────────────────────────── POST 分支（插在 /intent 之前）
ANCHOR = '''        if self.path.startswith("/intent"):'''
NEW_POSTS = '''        if self.path.startswith("/asr"):
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

        if self.path.startswith("/intent"):'''
assert ANCHOR in src, "POST 锚点没找到"
src = src.replace(ANCHOR, NEW_POSTS, 1)

# ─────────────────────────────────────────── 确保 PORT 在类里可见
if "PORT = int(os.environ.get" not in src and "PORT = 8765" in src:
    pass        # 模块级常量，类里能直接读

io.open(P, "w", encoding="utf-8").write(src)

import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("补丁完成, syntax OK")
print("新增接口数:", src.count('self._send(200, {"ok": True') )
