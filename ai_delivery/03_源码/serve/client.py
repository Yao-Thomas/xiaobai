# -*- coding: utf-8 -*-
"""
client.py —— 板端 / PC 端调用云端推理服务的客户端（带超时、重试、降级标志）

纯标准库 urllib，板端（Zynq Linux，可能没有 requests）也能直接用。

用法：
    cli = InferClient("http://192.168.1.50:8000", api_key="...", timeout=2.5)
    resp = cli.infer("waveform", samples)        # samples = 4096 个 0~255 采样
    resp = cli.infer("waveform", pixels, hint="image")
    if not resp.get("ok"):
        # 网络不可达/超时会带 offline=True（降级标志），板端据此提示"离线模式"
"""
import json
import socket
import time
import urllib.error
import urllib.request


class InferClient:
    def __init__(self, base_url, api_key=None, timeout=2.5, retries=1, backoff=0.3):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.timeout = float(timeout)
        self.retries = int(retries)
        self.backoff = float(backoff)

    # ------------------------------------------------------------------
    def infer(self, type_, data, hint=None, api_key=None):
        """按接口④契约构造请求并调用 /infer。"""
        payload = {"type": type_, "data": data}
        if hint is not None:
            payload["hint"] = hint
        key = api_key if api_key is not None else self.api_key
        if key:
            payload["api_key"] = key
        return self._post("/infer", payload)

    def infer_raw(self, payload):
        """直接发送已构造好的请求 dict（分级推理路由 cloud_predict 用）。"""
        payload = dict(payload)
        if self.api_key and "api_key" not in payload:
            payload["api_key"] = self.api_key
        return self._post("/infer", payload)

    # ------------------------------------------------------------------
    def _post(self, path, payload):
        url = self.base_url + path
        last_err = "unknown"
        for attempt in range(self.retries + 1):
            if attempt > 0:
                time.sleep(self.backoff)
            try:
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read().decode("utf-8")
                    try:
                        return json.loads(body)
                    except json.JSONDecodeError:
                        return {"ok": False,
                                "error": "云端返回非 JSON: %s" % body[:200]}
            except (urllib.error.URLError, urllib.error.HTTPError,
                    socket.timeout, TimeoutError, ConnectionError, OSError) as e:
                last_err = "%s: %s" % (type(e).__name__, e)
                continue
        return {
            "ok": False,
            "error": "云端不可达/超时（重试 %d 次后放弃）: %s" % (self.retries, last_err),
            "offline": True,          # ★ 降级标志，板端据此提示"离线模式"
        }
