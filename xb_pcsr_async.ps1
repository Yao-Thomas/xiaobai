# xb_pcsr_async.ps1 —— 流式语音识别：边说边出字
#
# ★ 为什么要这个（和 xb_pcsr.ps1 的区别）
# ────────────────────────────────────────────────────────────────
# xb_pcsr.ps1 用 Recognize(timeout)：**阻塞**，等你说完一整句、
#   静音 0.8 秒才返回。用户要的是"边说边出字"。
#
# 这个版本用 RecognizeAsync + 三个事件：
#     SpeechDetected     —— 检测到有人开始说话
#     SpeechHypothesized —— ★ 中间结果（还在猜，会变）
#     RecognizeCompleted —— 最终结果（定稿）
# 每拿到一个中间结果就立刻打一行出去，
# Python 侧边读边刷 UI ⇒ 就是"流式"。
#
# ★★★ 踩过的坑：不能用 Wait-Event 取事件
# ────────────────────────────────────────────────────────────────
# 第一版是 Register-ObjectEvent -Action {} 空着，
# 然后在主循环里 Wait-Event + Get-Event 取 —— **一条都取不到**。
# 原因：Register-ObjectEvent 把事件排到【后台 job 的 runspace】，
#       而 Wait-Event 看的是当前 runspace 的事件队列，两边不通。
# ⇒ 正确做法：在 -Action {} 里【直接】把结果写 stdout。
#   实测有效（TTS 生成的"现在多少度"依次吐出 现在 → 现在脱下 → 现在脱下肚）。
#
# ★ 输出协议（一行一条，Python 逐行读）：
#     START                    开始听了
#     HEARD                    检测到说话
#     PART|<中间结果>           ← 会变，UI 应该"刷新"而不是"追加"
#     FINAL|<最终结果>|<置信度>
#     ERR|<错误>
#
# 用法:
#   powershell -NoProfile -ExecutionPolicy Bypass -File xb_pcsr_async.ps1 -InitSecs 6 -TotalSecs 15
#   （加 -Wave 参数可以喂 WAV 文件，用于自测：-Wave D:\xxx.wav）

param(
    [int]$InitSecs = 6,
    [int]$TotalSecs = 15,
    [string]$Wave = ""
)

$ErrorActionPreference = "Continue"

try {
    Add-Type -AssemblyName System.Speech

    $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine
    if ($Wave -ne "" -and (Test-Path $Wave)) {
        $rec.SetInputToWaveFile($Wave)
    } else {
        $rec.SetInputToDefaultAudioDevice()
    }
    $rec.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))

    $rec.BabbleTimeout         = [TimeSpan]::FromSeconds(2)
    $rec.InitialSilenceTimeout = [TimeSpan]::FromSeconds($InitSecs)
    $rec.EndSilenceTimeout     = [TimeSpan]::FromSeconds(0.8)

    # ★ 事件回调里直接写 stdout（不要用 Wait-Event，取不到）
    $null = Register-ObjectEvent -InputObject $rec -EventName SpeechDetected `
        -Action { [Console]::Out.WriteLine("HEARD"); [Console]::Out.Flush() }
    $null = Register-ObjectEvent -InputObject $rec -EventName SpeechHypothesized `
        -Action {
            try {
                $t = $Event.SourceEventArgs.Result.Text
                if ($t) {
                    [Console]::Out.WriteLine("PART|" + $t)
                    [Console]::Out.Flush()
                }
            } catch { }
        }
    $null = Register-ObjectEvent -InputObject $rec -EventName RecognizeCompleted `
        -Action {
            try {
                $r = $Event.SourceEventArgs.Result
                if ($null -ne $r) {
                    $c = 0.0
                    try { $c = [double]$r.Confidence } catch { $c = 0.0 }
                    [Console]::Out.WriteLine("FINAL|" + $r.Text + "|" + $c)
                } else {
                    [Console]::Out.WriteLine("ERR|没听清（可能没说话）")
                }
            } catch {
                [Console]::Out.WriteLine("ERR|" + $_.Exception.Message)
            }
            [Console]::Out.Flush()
        }

    [Console]::Out.WriteLine("START")
    [Console]::Out.Flush()
    $rec.RecognizeAsync([System.Speech.Recognition.RecognizeMode]::Multiple)

    # ★ 等满 TotalSecs（FINAL 由事件自己吐，主线程只管计时）
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt $TotalSecs) {
        Start-Sleep -Milliseconds 150
    }
    try { $rec.RecognizeAsyncCancel() } catch { }
    Start-Sleep -Milliseconds 300
    Get-Event -ErrorAction SilentlyContinue | Remove-Event -ErrorAction SilentlyContinue
}
catch {
    $msg = $_.Exception.Message -replace "`r|`n", " "
    [Console]::Out.WriteLine("ERR|" + $msg)
    [Console]::Out.Flush()
}
