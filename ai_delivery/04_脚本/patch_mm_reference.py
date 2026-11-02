# -*- coding: utf-8 -*-
"""恢复 local_cnn 传输（服务端以视觉为主，端侧概率作参考）"""
import hashlib
import sys

T = "/home/zynq/ui/apps_scope_dual.py"
raw = open(T, "rb").read()
bom = raw.startswith(b"\xef\xbb\xbf")
if bom:
    raw = raw[3:]
s = raw.decode("utf-8")
print("before md5=%s" % hashlib.md5(raw).hexdigest())
CRLF = "\r\n" in s
if CRLF:
    s = s.replace("\r\n", "\n")
if "MM_REFERENCE_V2" in s:
    print("already")
    sys.exit(0)

OLD = '''            # MM_INDEPENDENT_V1：不把本地 CNN 结果传给云端
            #
            # 为什么要这么做：
            #   云端跑的是独立的 vision_v2 视觉模型（to_images -> 96x96 -> CNN）。
            #   如果先把本地 CNN 的结论塞给它，它就不再是「独立判断」，
            #   三者（本地 CNN / 本地模板 / 云端视觉）就退化成「一个说了算」。
            #   ⇒ 保留三路独立结论，界面上并列显示，互相验证。
            #
            #   （原来的 local_cnn 字段保留在代码里但不再发送，
            #     以后要做「云端参考本地」的实验可以直接打开。）
            _ = local  # noqa: F841'''

NEW = '''            # MM_REFERENCE_V2：传本地 8 类概率给云端，但云端「以自己分析为主」
            #
            # ★ 服务端的设计（见 wave_ai/analyzer.py 与 train.py 注释）：
            #   融合网络的三路输入是
            #     ① 96x96x3 视觉输入      ← 主
            #     ② 59 维手工特征         ← 主
            #     ③ 端侧 8 类概率         ← 参考
            #   训练时 p_drop=0.25 会随机把 ③ 丢掉，
            #   就是为了防止模型学成「抄端侧答案」。
            #   ⇒ 所以传过去是「参考」，不是「结论」，完全符合要求。
            #
            # ★ 必须传【完整 8 类概率 probs】，不能只传 label ——
            #   服务端 _parse_local_cnn() 要的是概率分布。
            if local:
                req["local_cnn"] = {
                    "label": local.get("label"),
                    "confidence": float(local.get("confidence") or 0.0),
                    "classes": ["sine", "square", "triangle", "sawtooth",
                                "noise", "clipping", "signal_loss",
                                "duty_abnormal"],
                    "probs": local.get("probs") or [],
                }'''

if OLD not in s:
    print("ERR anchor")
    i = s.find("MM_INDEPENDENT_V1")
    print(repr(s[max(0, i - 200):i + 400]))
    sys.exit(3)

s = s.replace(OLD, NEW, 1)
print("  + local_cnn restored (as reference, not truth)")

compile(s, T, "exec")
if CRLF:
    s = s.replace("\n", "\r\n")
out = s.encode("utf-8")
if bom:
    out = b"\xef\xbb\xbf" + out
open(T, "wb").write(out)
print("after md5=%s" % hashlib.md5(s.encode("utf-8")).hexdigest())
print("syntax ok")
