# -*- coding: utf-8 -*-
"""
demo_offline.py —— ★ 可现场演示的"拔网线降级"脚本

演示流程（对应契约 ④ 分级推理降级约定）：
    ① 启动一个"云端"（内置 stdlib HTTP 服务，返回固定高置信度结果）
    ② 正常请求：本地(启发式, 置信度 < 0.7) -> 送云端 -> 成功（decision_path=cloud）
    ③ 模拟拔网线：把客户端指向不可达地址 127.0.0.1:9 + 极短超时(0.3s) -> 云端超时
       -> 降级到本地 -> 打印"离线模式"（offline_mode=true, decision_path=cloud_fallback_local）
    ④ 恢复：把客户端指回云端 -> 自动回到云端路径（decision_path=cloud）

纯标准库 + 本项目 router/client/model_backend，无 fastapi 依赖，任何机器都能跑：
    python src/serve/demo_offline.py
"""
import json
import math
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.dirname(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import client  # noqa: E402
import model_backend  # noqa: E402
import router  # noqa: E402


# ---------------------------------------------------------------------------
# 内置"云端"（演示用固定高置信度响应）
# ---------------------------------------------------------------------------
class MockCloudHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path.startswith("/infer"):
            n = int(self.headers.get("Content-Length") or 0)
            _ = self.rfile.read(n) if n else b""
            resp = {"ok": True, "label": "square", "confidence": 0.93,
                    "detail": {"model_source": "mock_cloud",
                               "note": "云端大模型（演示用固定高置信度结果）"},
                    "elapsed_ms": 12}
            self._send_json(200, resp)
        else:
            self._send_json(404, {"ok": False, "error": "not found"})

    def _send_json(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # 静音访问日志
        pass


def start_mock_cloud(port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), MockCloudHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


# ---------------------------------------------------------------------------
# 演示输入：合成一段方波（4096 个 0~255 采样）
# ---------------------------------------------------------------------------
def make_square_samples(period=340, amp=90, n=4096, noise=1.5):
    out = []
    import random
    rng = random.Random(20261001)
    for i in range(n):
        v = 128 + amp if ((i % period) < period // 2) else 128 - amp
        v += rng.gauss(0, noise)
        out.append(max(0, min(255, int(round(v)))))
    return out


# ---------------------------------------------------------------------------
# 打印
# ---------------------------------------------------------------------------
def banner(text):
    print()
    print("=" * 72)
    print("  " + text)
    print("=" * 72)


def print_result(r):
    path = r.get("detail", {}).get("decision_path", "?")
    offline = r.get("offline_mode", False)
    if offline:
        print("  [降级] ★ 离线模式 —— 已降级到本地模型")
        print("  决策路径 : %s" % path)
        print("  云端错误 : %s" % r.get("detail", {}).get("cloud_error"))
    else:
        print("  [在线] 决策路径 : %s" % path)
    print("  结果     : ok=%s label=%s confidence=%s" %
          (r.get("ok"), r.get("label"), r.get("confidence")))
    print("  耗时     : %d ms" % r.get("elapsed_ms", -1))
    reason = r.get("detail", {}).get("reason")
    if reason:
        print("  原因     : %s" % reason)


# ---------------------------------------------------------------------------
def main():
    import argparse
    ap = argparse.ArgumentParser(description="分级推理·离线降级演示")
    ap.add_argument("--cloud-url", default="",
                    help="在线云端地址（缺省则启动内置模拟云端）")
    ap.add_argument("--offline-timeout", type=float, default=0.3,
                    help="模拟拔网线时的客户端超时(秒)")
    args = ap.parse_args()

    srv = None
    if args.cloud_url:
        cloud_url = args.cloud_url.rstrip("/")
    else:
        cloud_port = 18099
        srv = start_mock_cloud(cloud_port)
        cloud_url = "http://127.0.0.1:%d" % cloud_port

    local_backend = model_backend.HeuristicWaveformBackend()

    def local_predict(req):
        return local_backend.predict(req.get("data"), req.get("hint"))

    cli_online = client.InferClient(cloud_url, timeout=1.0, retries=0)

    def cloud_online(req):
        return cli_online.infer_raw(req)

    samples = make_square_samples()
    req = {"type": "waveform", "data": samples, "hint": "演示方波"}

    print("项目：系统管家小白 —— 分级推理·离线降级演示")
    print("本地模型 : %s（置信度阈值 0.7，本地启发式置信度 < 0.7 会送云端）"
          % local_backend.name)
    cloud_desc = "真实云端" if args.cloud_url else "内置模拟云端（固定返回 square/0.93）"
    print("云端     : %s（%s）" % (cloud_url, cloud_desc))

    banner("① 正常模式：云端可达")
    r = router.route(req, local_predict, cloud_online)
    print_result(r)

    banner("② 模拟拔网线：指向不可达地址 127.0.0.1:9 + 超时 %.1fs" % args.offline_timeout)
    cli_off = client.InferClient("http://127.0.0.1:9", timeout=args.offline_timeout,
                                 retries=0)

    def cloud_offline(req):
        return cli_off.infer_raw(req)

    r = router.route(req, local_predict, cloud_offline)
    print_result(r)

    banner("③ 恢复联网：自动回到云端")
    r = router.route(req, local_predict, cloud_online)
    print_result(r)

    banner("演示结束")
    print("结论：云端不可达/超时 -> 自动降级到本地并提示'离线模式'；")
    print("      网络恢复后无需重启，下一次请求自动回到云端。")
    if srv is not None:
        srv.shutdown()


if __name__ == "__main__":
    main()
