# xb_pcsr.ps1 —— 用 Windows 自带识别器听一句话，输出 JSON
#
# ★ 为什么单独一个文件而不是塞在 Python 里：
#   把 PowerShell 脚本放进 Python 的三引号字符串，会和 PS 里的引号打架
#   （踩过：`""text""` 把 Python 字符串提前结束了）。
#   写成独立 .ps1、用 -File 调最稳。
#
# ★ 文件要存成【带 BOM 的 UTF-8】，否则 PowerShell 5 读中文会乱码。
#
# 用法:
#   powershell -NoProfile -ExecutionPolicy Bypass -File xb_pcsr.ps1 -InitSecs 6 -TotalSecs 15
# 输出:
#   {"ok":true,"text":"现在多少度","conf":0.87}
#   {"ok":false,"error":"没听到说话（超时）"}

param(
    [int]$InitSecs = 6,
    [int]$TotalSecs = 15
)

$ErrorActionPreference = "Stop"

function Emit($obj) {
    # ★ 统一用 ConvertTo-Json 输出，别手工拼 —— 中文和引号都会出事
    $obj | ConvertTo-Json -Compress -Depth 3
}

try {
    Add-Type -AssemblyName System.Speech

    $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine
    $rec.SetInputToDefaultAudioDevice()

    # DictationGrammar = 自由听写（能认任意句子，不是只有预设命令词）
    $g = New-Object System.Speech.Recognition.DictationGrammar
    $rec.LoadGrammar($g)

    $rec.BabbleTimeout       = [TimeSpan]::FromSeconds(2)
    $rec.InitialSilenceTimeout = [TimeSpan]::FromSeconds($InitSecs)
    $rec.EndSilenceTimeout     = [TimeSpan]::FromSeconds(0.8)

    $r = $rec.Recognize([TimeSpan]::FromSeconds($TotalSecs))

    if ($null -eq $r) {
        Emit @{ ok = $false; error = "没听到说话（超时）" }
    } else {
        $c = 0.0
        try { $c = [double]$r.Confidence } catch { $c = 0.0 }
        Emit @{ ok = $true; text = $r.Text; conf = $c }
    }
}
catch {
    $msg = $_.Exception.Message -replace "`r|`n", " "
    Emit @{ ok = $false; error = $msg }
}
