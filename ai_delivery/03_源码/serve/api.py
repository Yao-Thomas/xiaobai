# -*- coding: utf-8 -*-
"""
api.py —— FastAPI 应用（云端推理服务 + 任务 H 同步接口）

★ 本文件依赖 fastapi/uvicorn/pydantic（lab415 环境已装：fastapi 0.115.6 /
  uvicorn 0.34.0 / pydantic 2.10.4）。开发机没有 fastapi 时，router/sync_store/
  client 的单测不受影响；本文件只需通过：
      python -c "import ast; ast.parse(open('src/serve/api.py',encoding='utf-8').read())"

启动：
    cd src/serve && /data/pengyc_fzu/envs/fpga2026/bin/python -m uvicorn api:app \
        --host 0.0.0.0 --port 8000
（或直接用 scripts/run_serve.sh）

契约（07_接口约定单.md 接口④）：
    POST /infer   {"type": "waveform"|"chat", "data": [...], "hint": "...", "api_key": "..."}
        成功 -> {"ok": true, "label": ..., "confidence": ..., "detail": {}, "elapsed_ms": ...}
        失败 -> {"ok": false, "error": "..."}

健壮性：任何异常都返回 {"ok": false, "error": "..."}，绝不 500 崩溃。
并发：阻塞调用（模型前向 / sqlite）放进线程池，不阻塞事件循环。
"""
import logging
import os
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.dirname(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.concurrency import run_in_threadpool  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

import config  # noqa: E402
import model_backend  # noqa: E402
import sync_store  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("serve")

if not config.API_KEY:
    log.warning("SERVE_API_KEY 未配置，/infer 与 /sync 将【不校验】api_key")

app = FastAPI(title="系统管家小白 · 云端推理服务", version="1.0.0")

# ---------------------------------------------------------------------------
# 全局单例 + 指标
# ---------------------------------------------------------------------------
_waveform_backend = None
_sync_store = None
_metrics = {"infer_total": 0, "infer_ok": 0, "infer_fail": 0, "by_type": {}}
_metrics_lock = threading.Lock()


def _get_waveform_backend():
    global _waveform_backend
    if _waveform_backend is None:
        _waveform_backend = model_backend.build_waveform_backend()
    return _waveform_backend


def _get_sync_store():
    global _sync_store
    if _sync_store is None:
        _sync_store = sync_store.SyncStore(config.SYNC_DB_PATH)
    return _sync_store


def _bump_metric(key):
    with _metrics_lock:
        _metrics[key] = _metrics.get(key, 0) + 1


def _bump_type(type_):
    with _metrics_lock:
        d = _metrics["by_type"]
        d[type_] = d.get(type_, 0) + 1


# ---------------------------------------------------------------------------
# 鉴权（简单鉴权：未配置不校验；配置后请求必须带匹配 api_key）
# ---------------------------------------------------------------------------
def _check_api_key(body):
    if not config.API_KEY:
        return True, None
    provided = body.get("api_key") if isinstance(body, dict) else None
    if provided == config.API_KEY:
        return True, None
    return False, "unauthorized: api_key 缺失或不匹配"


# ---------------------------------------------------------------------------
# 核心处理（线程池内执行的阻塞逻辑）
# ---------------------------------------------------------------------------
def _handle_infer(body):
    t0 = time.perf_counter()
    _bump_metric("infer_total")
    if isinstance(body, dict) and body.get("type") is not None:
        _bump_type(body.get("type"))

    ok, err = _check_api_key(body)
    if not ok:
        _bump_metric("infer_fail")
        return {"ok": False, "error": err}

    if not isinstance(body, dict) or "type" not in body or "data" not in body:
        _bump_metric("infer_fail")
        return {"ok": False, "error": "请求缺少必需字段 type/data"}

    try:
        resp = model_backend.run_cloud_inference(body)
    except Exception as e:  # noqa: BLE001 —— 任何异常都转 ok:false
        log.exception("infer 内部异常")
        _bump_metric("infer_fail")
        return {"ok": False, "error": "推理异常: %s" % e}

    resp["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
    if resp.get("ok"):
        _bump_metric("infer_ok")
    else:
        _bump_metric("infer_fail")
    return resp


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    """健康检查 + 当前配置（不泄露 API_KEY）。"""
    try:
        backend = _get_waveform_backend()
        model_source = backend.name
    except Exception as e:  # noqa: BLE001
        model_source = "unavailable: %s" % e
    return {
        "ok": True,
        "status": "up",
        "model_source": model_source,
        "config": config.to_dict(),
    }


@app.get("/metrics")
def metrics():
    with _metrics_lock:
        m = dict(_metrics)
        m["by_type"] = dict(m["by_type"])
    return {"ok": True, "metrics": m}


@app.post("/infer")
async def infer(request: Request):
    """接口④：云端推理。任何失败都返回 ok:false，绝不 500。"""
    try:
        body = await request.json()
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": "请求体不是合法 JSON: %s" % e},
                            status_code=200)
    result = await run_in_threadpool(_handle_infer, body)
    return JSONResponse(result, status_code=200)


@app.post("/sync/push")
async def sync_push(request: Request):
    """任务 H：客户端推记录（板子/PC）。body: {client_id, records:[...]}。"""
    try:
        body = await request.json()
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": "请求体不是合法 JSON: %s" % e},
                            status_code=200)
    ok, err = _check_api_key(body)
    if not ok:
        return JSONResponse({"ok": False, "error": err}, status_code=200)

    client_id = body.get("client_id") if isinstance(body, dict) else None
    records = body.get("records") if isinstance(body, dict) else None
    if not isinstance(records, list):
        return JSONResponse({"ok": False, "error": "records 必须是列表"}, status_code=200)
    try:
        result = await run_in_threadpool(
            lambda: _get_sync_store().push(client_id, records))
    except Exception as e:  # noqa: BLE001
        log.exception("sync_push 异常")
        return JSONResponse({"ok": False, "error": "同步异常: %s" % e}, status_code=200)
    return JSONResponse(result, status_code=200)


@app.get("/sync/pull")
def sync_pull(client_id: str = "board", since: int = 0, limit: int = 50,
              api_key: str = ""):
    """任务 H：增量拉取。since=上次 server_seq，limit=本次最多条数（板子传最近 N）。"""
    ok, err = _check_api_key({"api_key": api_key})
    if not ok:
        return JSONResponse({"ok": False, "error": err}, status_code=200)
    try:
        if limit <= 0:
            limit = config.BOARD_RECENT_N
        result = _get_sync_store().pull(client_id, since_seq=since, limit=limit)
    except Exception as e:  # noqa: BLE001
        log.exception("sync_pull 异常")
        return JSONResponse({"ok": False, "error": "同步异常: %s" % e}, status_code=200)
    return JSONResponse(result, status_code=200)
