#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llm.py —— DeepSeek 调用（带重试）

对应 DeepSeek Harness 的 `dsh-llm` / `dsh-llm-deepseek` / `dsh-llm-retry`。

两个板子上必须处理的现实问题：
  1. **TLS**：板子上系统 CA 用不了（实测 `CERTIFICATE_VERIFY_FAILED`），
     所以和浏览器一样做三级降级：正常 → 指定 CA 文件 → 不校验。
  2. **网络不稳**：AIC8800 这块卡会掉线。所以请求要重试（指数退避），
     并且把"网络错"和"API 错"分清楚 —— 前者重试，后者要把原文回给模型。
"""
import json
import os
import ssl
import time
import urllib.error
import urllib.request

from . import config

_SSL_MODE = None      # None / "sys" / "cafile" / "none"
CAFILES = ["/etc/ssl/certs/ca-certificates.crt",
           "/etc/pki/tls/certs/ca-bundle.crt"]


class LLMError(Exception):
    def __init__(self, msg, retryable=False, status=None):
        Exception.__init__(self, msg)
        self.retryable = retryable
        self.status = status


def _ctx(mode):
    if mode == "sys":
        return ssl.create_default_context()
    if mode == "cafile":
        for c in CAFILES:
            if os.path.exists(c):
                return ssl.create_default_context(cafile=c)
        return ssl._create_unverified_context()
    return ssl._create_unverified_context()


def chat(messages, tools=None, cfg=None, stream=False):
    """一次 chat/completions 调用（含重试）。返回解析后的 message dict。"""
    cfg = cfg or config.load()
    global _SSL_MODE
    if not cfg.get("api_key"):
        raise LLMError("没有配置 API key。设置环境变量 DEEPSEEK_API_KEY，"
                       "或写进 %s 的 api_key 字段" % config.CONF)

    url = cfg["api_base"].rstrip("/") + "/chat/completions"
    body = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": cfg.get("temperature", 0.3),
        "max_tokens": cfg.get("max_tokens", 2048),
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    modes = [_SSL_MODE] if _SSL_MODE else ["sys", "cafile", "none"]
    last = None
    tries = max(1, int(cfg.get("llm_retries", 3)))
    for attempt in range(tries):
        for mode in modes:
            try:
                req = urllib.request.Request(url, data=data, method="POST")
                req.add_header("Content-Type", "application/json")
                req.add_header("Authorization", "Bearer " + cfg["api_key"])
                t0 = time.time()
                r = urllib.request.urlopen(req, timeout=cfg.get("llm_timeout", 120),
                                           context=_ctx(mode))
                raw = r.read().decode("utf-8", "replace")
                _SSL_MODE = mode
                j = json.loads(raw)
                if "choices" not in j:
                    raise LLMError("返回里没有 choices：%s" % raw[:300])
                msg = j["choices"][0]["message"]
                msg["_usage"] = j.get("usage") or {}
                msg["_elapsed"] = time.time() - t0
                return msg
            except urllib.error.HTTPError as e:
                txt = ""
                try:
                    txt = e.read().decode("utf-8", "replace")
                except Exception:
                    pass
                last = LLMError("HTTP %s: %s" % (e.code, txt[:300]),
                                retryable=(e.code >= 500 or e.code == 429),
                                status=e.code)
                if e.code in (401, 403):
                    raise LLMError("API key 被拒（HTTP %s）。检查 key 是否正确/欠费。%s"
                                   % (e.code, txt[:200]))
                if not last.retryable:
                    raise last
            except ssl.SSLError as e:
                last = LLMError("TLS: %s" % e, retryable=False)
                continue                      # 换下一种 TLS 模式
            except urllib.error.URLError as e:
                s = str(getattr(e, "reason", e))
                retry = not any(k in s.upper() for k in
                                ("CERTIFICATE", "SSL"))
                last = LLMError("网络: %s" % s, retryable=retry)
                if not retry:
                    continue
            except Exception as e:
                last = LLMError("%s: %s" % (type(e).__name__, e), retryable=True)
        if last is not None and not last.retryable:
            break
        if attempt < tries - 1:
            wait = 1.5 * (attempt + 1)
            print("[llm] 第 %d 次失败（%s），%.1fs 后重试" % (attempt + 1, last, wait))
            time.sleep(wait)
    raise last or LLMError("未知错误")


def models(cfg=None):
    """列出可用模型（调试用）"""
    cfg = cfg or config.load()
    url = cfg["api_base"].rstrip("/") + "/models"
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Bearer " + cfg["api_key"])
    try:
        r = urllib.request.urlopen(req, timeout=20, context=_ctx(_SSL_MODE or "sys"))
        return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        r = urllib.request.urlopen(req, timeout=20,
                                   context=ssl._create_unverified_context())
        return json.loads(r.read().decode("utf-8", "replace"))
