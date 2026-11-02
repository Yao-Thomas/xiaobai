#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""xb_pcsr.py —— PC 端语音输入（Windows 自带的中文识别）

════════════════════════════════════════════════════════════════════
为什么用它（用户建议）
════════════════════════════════════════════════════════════════════
用户："语音输入完全可以接电脑自己的语音输入啊，对吧，电脑软件好处理吧"

对。之前那版是【PC 录音 → 上传给板子 → 板子转发百度 → 返回文字】，
绕一大圈：录音要传、板子要联网、百度 key 失效就废。

而 Windows 自带中文识别器（这台机器实测有）：
    zh-CN  Microsoft Speech Recognizer 8.0 for Windows (Chinese Simplified - PRC)
★ 完全离线、零依赖、亚秒级返回。

════════════════════════════════════════════════════════════════════
怎么调
════════════════════════════════════════════════════════════════════
Windows 的 System.Speech 是 .NET 的，Python 调不了，所以起 PowerShell 子进程：
    ① SpeechRecognitionEngine + SetInputToDefaultAudioDevice
    ② 加载 DictationGrammar（自由听写，不是命令词）
    ③ Recognize(timeout) 阻塞等一句话
    ④ 用 ConvertTo-Json 输出（★ 别手工拼 JSON，引号会打架 —— 踩过）

★ 为什么不用 RecognizeAsync：子进程里同步等更简单，
  而且交互本来就是"说一句、拿一句"。

★ 实现注意（踩过）：
  · PowerShell 脚本【写进临时 .ps1 文件】再 -File 执行，
    不要在命令行 -Command 里塞多行中文脚本（编码会乱）
  · .ps1 要带 UTF-8 BOM，否则 PowerShell 读中文会乱码
  · Python 源码里也别用三引号套 PowerShell 的引号 —— 直接读 .ps1 文件最稳
════════════════════════════════════════════════════════════════════
"""
import json
import os
import subprocess
import sys
import tempfile
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))


def _ps_path():
    """找 xb_pcsr.ps1 的位置

    ★★★ 打包成 exe 后【不能】用 __file__ 找同级文件（踩过）：
        PyInstaller onefile 会把 Python 模块解到临时目录 sys._MEIPASS，
        而 --add-data 塞进去的数据文件也在那里；
        但 __file__ 指向的位置和实际解压目录不一定一致。
    ⇒ 判 frozen 就用 sys._MEIPASS。
      同时【打包时必须带 --add-data "xb_pcsr.ps1;."】，
      否则 exe 里根本没有这个文件（这个坑我踩过：
      模块打进去了、脚本没打进去，点语音就报"缺少 xb_pcsr.ps1"）。
    """
    cands = []
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        cands.append(os.path.join(base, "xb_pcsr.ps1"))
        cands.append(os.path.join(os.path.dirname(sys.executable),
                                  "xb_pcsr.ps1"))
    cands.append(os.path.join(HERE, "xb_pcsr.ps1"))
    for c in cands:
        if os.path.exists(c):
            return c
    return cands[-1]


PS_FILE = _ps_path()

_AVAIL = None
_LANGS = []


def available():
    """PC 上有没有可用的中文识别器（结果缓存）"""
    global _AVAIL
    if _AVAIL is not None:
        return _AVAIL
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Add-Type -AssemblyName System.Speech; "
             "[System.Speech.Recognition.SpeechRecognitionEngine]"
             "::InstalledRecognizers() | ForEach-Object { $_.Culture.Name }"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace")
        langs = [ln.strip() for ln in (p.stdout or "").split("\n") if ln.strip()]
        _AVAIL = any(x.lower().startswith("zh") for x in langs)
        _LANGS[:] = langs
    except Exception:
        _AVAIL = False
    return _AVAIL


def langs():
    available()
    return list(_LANGS)


def listen(init_secs=6, total_secs=15):
    """听一句话，返回 (文字, 错误)

    init_secs : 等用户开口的时间（超了就返回"没听到"）
    total_secs: 整句最长等多久
    ★ 这个函数会【阻塞】，调用方放到后台线程里。
    """
    if not available():
        return None, "这台电脑没有中文语音识别器（Windows 语音识别）"
    if not os.path.exists(PS_FILE):
        return None, "缺少 %s" % os.path.basename(PS_FILE)
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", PS_FILE,
             "-InitSecs", str(int(init_secs)), "-TotalSecs", str(int(total_secs))],
            capture_output=True, text=True, timeout=total_secs + 20,
            encoding="utf-8", errors="replace")
        out = (p.stdout or "").strip()
        # 取最后一行 JSON（PS 可能混别的输出）
        for ln in reversed(out.split("\n")):
            ln = ln.strip()
            if ln.startswith("{"):
                try:
                    d = json.loads(ln)
                    if d.get("ok"):
                        return (d.get("text") or "").strip(), None
                    return None, d.get("error") or "识别失败"
                except Exception:
                    continue
        return None, ("识别器没返回结果："
                      + (out[:120] or (p.stderr or "")[:120]))
    except subprocess.TimeoutExpired:
        return None, "识别超时"
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)


def listen_async(cb, init_secs=6, total_secs=15):
    """异步版：听完调 cb(text, err)（在后台线程里）"""
    def work():
        t, e = listen(init_secs, total_secs)
        try:
            cb(t, e)
        except Exception:
            pass
    threading.Thread(target=work, daemon=True).start()


# ══════════════════════════════════════════════════════════════════
#  ★★★ 流式识别（2026-10-03）—— 边说边出字
# ══════════════════════════════════════════════════════════════════
# 路线图 P1 第 1a 项要的"流式语音输入"。
#
# 之前（listen）：Recognize(timeout) 阻塞，等你说完整句 + 静音 0.8 秒
#                才一次性返回 ⇒ 感觉在干等。
# 现在（listen_stream）：用 RecognizeAsync，Windows 每猜一点就吐一个
#                中间结果，我们边读边回调 ⇒ 字跟着嘴出来。
#
# ★ 怎么读到的：PowerShell 子进程一行一条地输出
#     PART|<中间结果>    ← 会变，UI 应该【替换】而不是追加
#     FINAL|<最终结果>|<置信度>
#     ERR|<错误>
#   用 Popen + 逐行读（不能等进程结束，否则就退回一次性了）。
#
# ★ 自测办法：给 wave 参数喂一个 WAV 文件
#   （tts_gen.ps1 能用 Windows 的 TTS 生成中文语音），
#   不用真人对麦克风说话就能验证整条链路。
# ══════════════════════════════════════════════════════════════════
PS_ASYNC = os.path.join(HERE, "xb_pcsr_async.ps1")


def _ps_async_path():
    """找流式脚本的路径（打包后要在 sys._MEIPASS 里找）"""
    cands = []
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        cands.append(os.path.join(base, "xb_pcsr_async.ps1"))
        cands.append(os.path.join(os.path.dirname(sys.executable),
                                  "xb_pcsr_async.ps1"))
    cands.append(PS_ASYNC)
    for c in cands:
        if os.path.exists(c):
            return c
    return cands[-1]


def listen_stream(on_part=None, on_final=None, on_heard=None,
                  init_secs=6, total_secs=15, wave=None):
    """★ 流式识别：边说边回调，返回 (最终文字, 错误)

    on_part(text)          中间结果（会反复变，UI 应替换显示）
    on_final(text, conf)   最终结果
    on_heard()             检测到有人开始说话
    wave                   ★ 传 WAV 路径就从文件读（自测用）

    ★ 这个函数【阻塞】（逐行读子进程输出），调用方要放到后台线程里。
    """
    if not available():
        return None, "这台电脑没有中文语音识别器（Windows 语音识别）"
    ps = _ps_async_path()
    if not os.path.exists(ps):
        return None, "缺少 %s" % os.path.basename(ps)

    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-File", ps, "-InitSecs", str(int(init_secs)),
           "-TotalSecs", str(int(total_secs))]
    if wave:
        cmd += ["-Wave", wave]

    final_text = None
    conf = 0.0
    err = None
    proc = None
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", bufsize=1)
        # ★ 逐行读：这就是"流式"的关键 —— 不等进程结束
        for raw in proc.stdout:
            line = (raw or "").strip()
            if not line:
                continue
            if line == "START":
                continue
            if line == "HEARD":
                if on_heard:
                    try:
                        on_heard()
                    except Exception:
                        pass
                continue
            if line.startswith("PART|"):
                _t = line[5:].strip()
                if _t and on_part:
                    try:
                        on_part(_t)
                    except Exception:
                        pass
                continue
            if line.startswith("FINAL|"):
                parts = line.split("|")
                final_text = parts[1].strip() if len(parts) > 1 else ""
                if len(parts) > 2:
                    try:
                        conf = float(parts[2])
                    except Exception:
                        conf = 0.0
                if on_final:
                    try:
                        on_final(final_text, conf)
                    except Exception:
                        pass
                break
            if line.startswith("ERR|"):
                err = line[4:].strip()
                break
        try:
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)
    finally:
        try:
            if proc and proc.poll() is None:
                proc.kill()
        except Exception:
            pass

    if final_text:
        return final_text, None
    return None, (err or "没听清")


def listen_stream_async(on_part=None, on_final=None, on_heard=None,
                        init_secs=6, total_secs=15, done=None):
    """流式的异步包装：把 listen_stream 放到后台线程跑

    ★ 为什么需要它：listen_stream 是阻塞的（逐行读子进程），
      直接在主线程调会把界面冻住。而且回调是【后台线程】里触发的，
      调用方如果碰 tkinter，必须自己 q.put 回主线程。
    """
    def work():
        t, e = listen_stream(on_part=on_part, on_final=on_final,
                             on_heard=on_heard, init_secs=init_secs,
                             total_secs=total_secs)
        if done:
            try:
                done(t, e)
            except Exception:
                pass
    threading.Thread(target=work, daemon=True).start()


if __name__ == "__main__":
    print("语言:", langs() or "（无）")
    print("可用:", available())
    if not available():
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1].endswith(".wav"):
        # ★ 自测：喂 WAV，不用真人说话
        print("流式识别（喂 WAV）:", sys.argv[1])
        t, e = listen_stream(on_part=lambda x: print("  PART:", x),
                             on_final=lambda x, c: print("  FINAL:", x, c),
                             wave=sys.argv[1])
        print("结果:", repr(t), "错误:", e)
    else:
        print("说一句话（边说边出字）...")
        t, e = listen_stream(on_part=lambda x: print("  PART:", x),
                             on_final=lambda x, c: print("  FINAL:", x, c))
        print("结果:", repr(t), "错误:", e)
