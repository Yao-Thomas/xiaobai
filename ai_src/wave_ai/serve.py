"""
serve.py —— HTTP 服务（契约 §1/§2/§3 的落地实现）

端点：
    GET  /health               健康检查（契约 §2.4 / §3.4）
    POST /waveform/analyze     多模态合一（主接口，契约 §3.1）
    POST /waveform/classify    视觉模型（契约 §2.3）
    POST /waveform/explain     语言模型（契约 §3.2）

★ 硬性要求的实现方式
   1. 一律 HTTP + JSON（UTF-8 无 BOM）：手动编码 utf-8，Content-Length 精确。
   2. 失败必须 **HTTP 200 + {"ok": false, "error": "..."}**：
      handler 里所有异常都被捕获成 ok:false，绝不返回 4xx/5xx（板端网络栈弱）。
   3. classes 与 probs 等长、顺序一致、和为 1：由 analyzer 保证并单测。
   4. 纯标准库 HTTP 服务（无 fastapi/flask 依赖）——板端/PC 端都好部署。

启动：
    python -m wave_ai.serve --port 8000 --model runs/v2_full/model_bundle.pt
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .analyzer import Analyzer
from .config import ENGINE, VERSION

MAX_BODY = 8 * 1024 * 1024


def _json_bytes(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "WaveAI/%s" % VERSION

    # ---------------- 基础 ----------------
    def _send(self, obj, code=200):
        body = _json_bytes(obj)
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0:
            return {}
        if n > MAX_BODY:
            raise ValueError("请求体过大（%d 字节）" % n)
        raw = self.rfile.read(n)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8", errors="replace"))

    def log_message(self, fmt, *args):  # 精简日志
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    # ---------------- 路由 ----------------
    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/health", "/"):
            try:
                h = self.server.analyzer.health()
            except Exception as e:  # pragma: no cover
                return self._send({"ok": False, "engine": ENGINE, "error": str(e)})
            if path == "/":
                h["usage"] = {
                    "POST /waveform/analyze": "多模态合一分析（契约 §3.1）",
                    "POST /waveform/classify": "视觉模型分类（契约 §2.3）",
                    "POST /waveform/explain": "语言模型解释（契约 §3.2）",
                }
            return self._send(h)
        return self._send({"ok": False, "engine": ENGINE,
                           "error": "未知路径 %s（可用：/health, /waveform/analyze, "
                                    "/waveform/classify, /waveform/explain）" % path})

    def do_POST(self):
        path = self.path.split("?")[0]
        t0 = time.perf_counter()
        try:
            body = self._read_json()
        except Exception as e:
            return self._send({"ok": False, "engine": ENGINE,
                               "error": "请求体不是合法 JSON：%s" % str(e)[:160]})
        a = self.server.analyzer
        try:
            if path == "/waveform/analyze":
                resp = a.analyze(body)
            elif path == "/waveform/classify":
                resp = a.classify(body)
            elif path == "/waveform/explain":
                resp = a.explain(body)
            else:
                return self._send({"ok": False, "engine": ENGINE,
                                   "error": "未知路径 %s" % path})
            resp.setdefault("server_ms", int(round((time.perf_counter() - t0) * 1000)))
            return self._send(resp)
        except Exception as e:  # pragma: no cover - 最后一道防线
            sys.stderr.write(traceback.format_exc())
            return self._send({"ok": False, "engine": ENGINE,
                               "error": "%s: %s" % (type(e).__name__, str(e)[:200])})


def make_server(analyzer, host="0.0.0.0", port=8000):
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    srv.analyzer = analyzer
    return srv


def _lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    ap = argparse.ArgumentParser(description="多模态波形分析服务")
    ap.add_argument("--model", default="runs/v2_full/model_bundle.pt")
    ap.add_argument("--anomaly", default=None,
                    help="异常检测统计量（默认找模型同目录的 anomaly_stats.npz）")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args()

    stats = args.anomaly
    if stats is None:
        cand = os.path.join(os.path.dirname(os.path.abspath(args.model)),
                            "anomaly_stats.npz")
        stats = cand if os.path.exists(cand) else None

    print("=" * 64)
    print(" 多模态波形分析服务 v%s" % VERSION)
    print(" 模型   : %s" % args.model)
    print(" 异常库 : %s" % (stats or "（未找到，异常检测降级为仅置信度）"))
    a = Analyzer(args.model, stats, threads=args.threads)
    h = a.health()
    print(" 类别   : %d 类  %s" % (h["n_classes"], ",".join(h["classes"])))
    print(" 指标   : %s" % h["metrics"])
    print(" 加载   : %.0f ms" % h["load_ms"])
    srv = make_server(a, args.host, args.port)
    ip = _lan_ip() if args.host == "0.0.0.0" else args.host
    print("-" * 64)
    print(" 监听   : http://%s:%d" % (args.host, args.port))
    print(" 板端填 : http://%s:%d" % (ip, args.port))
    print(" 健康检查: curl http://%s:%d/health" % (ip, args.port))
    print("=" * 64, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
