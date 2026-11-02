# -*- coding: utf-8 -*-
"""
router.py —— ★ 分级推理核心逻辑（不依赖 fastapi，纯函数，便于单测）

契约（07_接口约定单.md 接口④ + 00_接口冻结单.md §6）：
    ① 板子优先用本地量化小模型
    ② 置信度 < 阈值（0.7）或请求类型未知 -> 送云端
    ③ 云端不可达/超时 -> 降级到本地，置 offline_mode=true，明确提示"离线模式"
    ④ 联网后自动恢复（每次请求独立判断，无需重启）

决策路径记录到返回的 detail.decision_path，便于演示时讲清楚：
    "local"                本地置信度足够，未走云端
    "cloud"                送云端且云端成功
    "cloud_fallback_local" 云端失败，降级回本地（离线模式）

返回结构 = 契约成功响应 + 顶层 offline_mode（布尔，恒存在，便于板端直接判断）：
    {"ok": true, "label": ..., "confidence": ..., "detail": {...}, "elapsed_ms": ..., "offline_mode": false}
"""
import time

import config

KNOWN_TYPES = {"waveform", "chat"}


def _now_ms(t0):
    return int((time.perf_counter() - t0) * 1000)


def _safe_call(fn, request, name):
    """调用注入的 local_predict/cloud_predict，任何异常都转成 ok:false，绝不向上抛。"""
    try:
        return fn(request)
    except Exception as e:  # noqa: BLE001 —— 演示/生产都必须吞掉，不能 500
        return {"ok": False, "error": "%s 异常: %s" % (name, e)}


def route(request, local_predict, cloud_predict, threshold=None):
    """分级推理路由。

    参数
    ----
    request        : dict，至少含 "type"（可选 "data"/"hint"/"api_key"）
    local_predict  : callable(request) -> {"ok", "label", "confidence", "detail"}
                     或 {"ok": False, "error"}
    cloud_predict  : callable(request) -> 同上（云端成功时可带 "elapsed_ms"）
    threshold      : 置信度阈值；默认 config.CONFIDENCE_THRESHOLD

    返回
    ----
    契约响应 dict，另带顶层 offline_mode（bool）与 detail.decision_path。
    """
    if threshold is None:
        threshold = config.CONFIDENCE_THRESHOLD
    t0 = time.perf_counter()

    req_type = request.get("type") if isinstance(request, dict) else None
    type_known = req_type in KNOWN_TYPES

    # ① 本地优先
    local_resp = _safe_call(local_predict, request, "local_predict")
    local_ok = bool(local_resp.get("ok"))
    local_conf = local_resp.get("confidence") if local_ok else None

    # ② 是否需要云端：类型未知 / 本地失败 / 本地无置信度 / 置信度低于阈值
    need_cloud = (
        (not type_known)
        or (not local_ok)
        or (local_conf is None)
        or (local_conf < threshold)
    )

    routing = {
        "confidence_threshold": threshold,
        "local_confidence": local_conf,
        "type_known": type_known,
    }

    if not need_cloud:
        routing.update({
            "decision_path": "local",
            "offline_mode": False,
            "reason": "本地置信度 %.3f >= 阈值 %.2f，无需云端" % (local_conf, threshold),
        })
        return _finalize(local_resp, routing, t0)

    # ③ 送云端
    cloud_resp = _safe_call(cloud_predict, request, "cloud_predict")
    if cloud_resp.get("ok"):
        routing.update({
            "decision_path": "cloud",
            "offline_mode": False,
            "reason": _cloud_reason(req_type, local_ok, local_conf, threshold),
            "cloud_elapsed_ms": cloud_resp.get("elapsed_ms"),
        })
        return _finalize(cloud_resp, routing, t0)

    # ④ 云端失败 -> 降级到本地（离线模式）
    routing.update({
        "decision_path": "cloud_fallback_local",
        "offline_mode": True,
        "reason": "云端不可达/超时，降级到本地（离线模式）",
        "cloud_error": cloud_resp.get("error"),
    })
    if local_ok:
        return _finalize(local_resp, routing, t0)

    # 本地也不可用 -> 整体失败
    return {
        "ok": False,
        "error": cloud_resp.get("error") or "云端与本地推理均失败",
        "detail": routing,
        "elapsed_ms": _now_ms(t0),
        "offline_mode": True,
    }


def _cloud_reason(req_type, local_ok, local_conf, threshold):
    if not req_type or req_type not in KNOWN_TYPES:
        return "请求类型未知 -> 送云端"
    if not local_ok:
        return "本地推理失败 -> 送云端"
    if local_conf is None:
        return "本地无置信度 -> 送云端"
    return "本地置信度 %.3f < 阈值 %.2f -> 送云端" % (local_conf, threshold)


def _finalize(resp, routing, t0):
    """把被选中的 local/cloud 响应包装成契约形状，合并路由决策到 detail。"""
    detail = dict(resp.get("detail") or {})
    detail.update(routing)                      # 路由决策信息覆盖/并入 detail
    out = {
        "ok": bool(resp.get("ok")),
        "detail": detail,
        "elapsed_ms": _now_ms(t0),
        "offline_mode": bool(routing.get("offline_mode", False)),
    }
    if out["ok"]:
        out["label"] = resp.get("label")
        out["confidence"] = resp.get("confidence")
    else:
        out["error"] = resp.get("error")
    return out
